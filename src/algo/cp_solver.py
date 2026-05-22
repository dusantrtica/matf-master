from collections import defaultdict
from ortools.sat.python import cp_model
from typing import List
from src.algo.data import Session, generate_sessions, GROUP_SIZE
from src.algo.model import (
    SchedulingInput,
    Settings,
    Course,
)
from src.rules.base import SchedulingRule
from src.rules.general.rule_join_same_classes import JoinSameClassesRule

RULE_REGISTRY: dict[str, type[SchedulingRule]] = {
    "joinSameClasses": JoinSameClassesRule,
}

class SimpleCPSolver:
    """
    Klasa SimpleCPSolver, koristi CP rešavač da napravi raspored nastave
    """
    def __init__(
        self,
        scheduling_input: SchedulingInput,        
        max_time_seconds: float = 30.0,
        log_progress: bool = True,
    ):
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()
        self.solver.parameters.max_time_in_seconds = max_time_seconds
        self.solver.parameters.log_search_progress = log_progress

        # Ubrzava rešavanje tako sto koristimo vise jezgara i tako sto
        # skracujemo simetrije u modelu.
        self.solver.parameters.num_search_workers = 8  # use all M4 cores
        self.solver.parameters.symmetry_level = 2

        self.init_input(scheduling_input)
        
        self.create_assignment_variables()
        self.create_hard_constraints()
        self.apply_rules()

    def init_input(self, scheduling_input: SchedulingInput):
        self.scheduling_input = scheduling_input
        self.settings: Settings = scheduling_input.settings
        self.classrooms = scheduling_input.classrooms
        self.courses: List[Course] = scheduling_input.courses
        self.departments = scheduling_input.departments
        self.students_enrolled = scheduling_input.students_enrolled
        self.working_hours = [
            hour for hour in range(self.settings.start_hour, self.settings.end_hour)
        ]
        self.sessions = generate_sessions(scheduling_input, GROUP_SIZE)

    def create_assignment_variables(self):
        """
        Za svaku sesiju (sesija je jedno predavanje u vremenskoj jedinici 1 čas)
        imamo 5 promenljivih
          day_var[s]       -- koji radni dan (0..D-1, Pon, Utorak, ..., Petak)
          slot_var[s]      -- koji sat u toku radnog dana (0..H-1)
          room_var[s]      -- koju učionicu će zauzeti (0..R-1)
          flat_time_var[s] -- apsolutuna vrednost vremena u nedelji u odnosu na početak nedelje (ponedeljak, 8č)
          room_time_var[s] -- apsolutna vrendost učionica u datom vremenu: room * D*H + flat_time
        """
        D = len(self.settings.working_days)
        H = len(self.working_hours)
        R = len(self.classrooms)
        total_slots = D * H

        self.day_var: dict[int, cp_model.IntVar] = {}
        self.slot_var: dict[int, cp_model.IntVar] = {}
        self.room_var: dict[int, cp_model.IntVar] = {}
        self.flat_time_var: dict[int, cp_model.IntVar] = {}
        self.room_time_var: dict[int, cp_model.IntVar] = {}

        for s in range(len(self.sessions)):
            self.day_var[s] = self.model.NewIntVar(0, D - 1, f"day_{s}")
            self.slot_var[s] = self.model.NewIntVar(0, H - 1, f"slot_{s}")
            self.room_var[s] = self.model.NewIntVar(0, R - 1, f"room_{s}")

            # flat_time konvertuje (day, slot) u jedinstven indeks 
            #   Ponedeljak slot 0 -> 0, Ponedeljak slot 1 -> 1, ...
            #   Utorak slot 0 -> H, Utorak slot 1 -> H+1, ...
            #  ova promenljiva nam treba da bismo postavili ograničenje AllDifferent
            #  da se nikoje 2 sesije (predavanja ne održavaju u istom vremenskom trenutku)
            self.flat_time_var[s] = self.model.NewIntVar(
                0, total_slots - 1, f"flat_time_{s}"
            )

            # ogranicenje da flat_time bude jednak day * H + slot, da bude smisleno mapiranje
            self.model.Add(
                self.flat_time_var[s] == self.day_var[s] * H + self.slot_var[s]
            )

            # room_time linearizuje, tj. konvertuje trojku (room, day, slot) u jedinstven indeks, offset
            # tako da AllDifferent osigura da nikoje 2 sesije ne dele istu vrendost room i vreme
            self.room_time_var[s] = self.model.NewIntVar(
                0, R * total_slots - 1, f"room_time_{s}"
            )
            self.model.Add(
                self.room_time_var[s]
                == self.room_var[s] * total_slots + self.flat_time_var[s]
            )

    def create_hard_constraints(self):
        """
        Hard constraint 1: Nikoje 2 sesije ne mogu biti u istoj učionici u datom satu-danu
        Hard constraint 2: Nikoje 2 sesije za istu grupu tj. tok ne mogu biti u istom trenutku
        Npr. Tok A informatika ne može imati 2 različita predavanja u utorak u 10č
        Hard constraint 3: Sessions needing computers go to rooms that have them.
        """
        if not self.sessions:
            return

        # 1) Sve vrednosti room-time moraju biti medjusobno razlicite
        self.model.AddAllDifferent(list(self.room_time_var.values()))

        # 2) Jedna grupa ne moze imati 2 razlicita predavanja u isto vreme
        # uzimamo sve sesije jedne grupe i trazimo da flat_time budu razlicite
        groups = defaultdict(list)
        for s, session in enumerate(self.sessions):
            groups[session.group_id].append(s)

        for group_id, session_indices in groups.items():
            self.model.AddAllDifferent([self.flat_time_var[s] for s in session_indices])

        # 3) sesije koje zahtevaju racunare, moraju imati ucionice sa racunarima
        # uzimamo indekse ucionica sa racunarima
        computer_room_indices = [
            i for i, room in enumerate(self.classrooms) if room.has_computers
        ]
        for s, session in enumerate(self.sessions):
            if session.needs_computers:
                # predavanje koje zahteva racunare, moze uzeti samo
                # oredjenedozvoljene vrednosti.
                self.model.AddAllowedAssignments(
                    [self.room_var[s]],
                    [[idx] for idx in computer_room_indices],
                )

    def apply_rules(self):
        """Instantiate and apply all enabled rule plugins from config."""
        self.penalty_vars: list[tuple[int, cp_model.IntVar]] = []

        for rule_name, config in self.scheduling_input.rules.items():
            if not config.enabled:
                continue
            rule_class = RULE_REGISTRY.get(rule_name)
            if rule_class is None:
                raise ValueError(f"Unknown rule: '{rule_name}'")
            rule = rule_class(enabled=config.enabled, penalty=config.penalty)
            violations = rule.apply(self)
            for v in violations:
                self.penalty_vars.append((config.penalty, v))

        if self.penalty_vars:
            self.model.Minimize(
                sum(weight * var for weight, var in self.penalty_vars)
            )

    def solve(self):
        status = self.solver.Solve(self.model)
        return status

    def get_solution_variables(self):
        """
        Nakon solve(), izvucemo dodeljeni dan, sat i indeks ucionice za svaku sesiju.
        Vraća raw indekse tako da pozivalac mapira indekse na nazive
        koristeći settings.working_days, working_hours i classrooms.
        """
        result = []
        for s in range(len(self.sessions)):
            day_index = self.solver.Value(self.day_var[s])
            slot_index = self.solver.Value(self.slot_var[s])
            room_index = self.solver.Value(self.room_var[s])
            result.append(
                {
                    "day": day_index,
                    "hour": slot_index,
                    "room": room_index,
                }
            )
        return result
