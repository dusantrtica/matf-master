from collections import defaultdict
from ortools.sat.python import cp_model
from typing import List
from src.algo.data import (
    Session,
    generate_sessions,
    GROUP_SIZE,
)
from src.algo.model import (
    SchedulingInput,
    StaffInput,
    Settings,
    Course,
)
from src.rules.base import SchedulingRule
from src.rules.general.rule_join_same_classes import JoinSameClassesRule
from src.rules.general.rule_single_location_in_day_for_group import SingleLocationInDayForGroupRule
from src.rules.general.rule_no_gaps_in_schedule import NoGapsInScheduleRule
from src.rules.general.rule_prefer_larger_rooms import PreferLargerRoomsForLargerSessionsRule
from src.rules.staff.rule_staff_max_working_days import StaffMaxWorkingDaysRule
from src.rules.staff.rule_staff_no_gap_greater_than import StaffMaxGapHoursRule
from src.rules.staff.rule_staff_single_location_in_day import StaffSingleLocationInDayRule

RULE_REGISTRY: dict[str, type[SchedulingRule]] = {
    "joinSameClasses": JoinSameClassesRule,
    "singleLocationInDayForGroup": SingleLocationInDayForGroupRule,
    "noGapsInSchedule": NoGapsInScheduleRule,
    "preferLargerRoomsForLargerSessions": PreferLargerRoomsForLargerSessionsRule,
    "staffMaxWorkingDays": StaffMaxWorkingDaysRule,
    "staffMaxGapHoursPerWeek": StaffMaxGapHoursRule,
    "staffSingleLocationInDay": StaffSingleLocationInDayRule,
}

class SimpleCPSolver:
    """
    Klasa SimpleCPSolver, koristi CP rešavač da napravi raspored nastave
    """
    def __init__(
        self,
        scheduling_input: SchedulingInput,
        staff_input: StaffInput | None = None,
        max_time_seconds: float = 30.0,
        log_progress: bool = True,
    ):
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()
        self.solver.parameters.max_time_in_seconds = max_time_seconds
        self.solver.parameters.log_search_progress = log_progress

        # Ubrzava rešavanje tako sto koristimo vise jezgara i tako sto
        # skracujemo simetrije u modelu, npr sve ucionice su jednake po izboru
        # isto je dal sesija ide u ucionicu 0, ili 1, ili 2.
        self.solver.parameters.num_search_workers = 8  # use all M4 cores
        self.solver.parameters.symmetry_level = 2

        self.init_input(scheduling_input, staff_input)

        self.create_assignment_variables()
        self.create_hard_constraints()
        self.apply_rules()

    def init_input(
        self,
        scheduling_input: SchedulingInput,
        staff_input: StaffInput | None = None,
    ):
        self.scheduling_input = scheduling_input
        self.staff_input = staff_input
        self.teachers = staff_input.teachers if staff_input else []
        self.settings: Settings = scheduling_input.settings
        self.classrooms = scheduling_input.classrooms
        self.courses: List[Course] = scheduling_input.courses
        self.tracks = scheduling_input.tracks
        self.students_enrolled = scheduling_input.students_enrolled
        self.working_hours = [
            hour for hour in range(self.settings.start_hour, self.settings.end_hour)
        ]
        # dodele iz staff fajla odredjuju i zajednicke sesije (kohorte)
        # i nastavnika svake sesije
        self.sessions = generate_sessions(scheduling_input, GROUP_SIZE, staff_input)

        # teacher_id -> globalni indeksi sesija tog nastavnika
        self.teacher_sessions: dict[int, list[int]] = defaultdict(list)
        for s, session in enumerate(self.sessions):
            if session.teacher_id is not None:
                self.teacher_sessions[session.teacher_id].append(s)

    def create_assignment_variables(self):
        """
        Za svaku sesiju (sesija je jedno predavanje u vremenskoj jedinici 1 čas)
        imamo 6 promenljivih
          day_var[s]       -- koji radni dan (0..D-1, Pon, Utorak, ..., Petak)
          slot_var[s]      -- koji sat u toku radnog dana (0..H-1)
          room_var[s]      -- koju učionicu će zauzeti (0..R-1)
          flat_time_var[s] -- apsolutuna vrednost vremena u nedelji u odnosu na početak nedelje (ponedeljak, 8č)
          room_time_var[s] -- apsolutna vrendost učionica u datom vremenu: room * D*H + flat_time
          loc_var[s]       -- loc_id lokacije na kojoj se nalazi dodeljena učionica
        """
        D = len(self.settings.working_days)
        H = len(self.working_hours)
        R = len(self.classrooms)
        total_slots = D * H
        locations_of_classrooms = [c.loc_id for c in self.classrooms]
        max_loc = max(locations_of_classrooms, default=0)

        self.day_var: dict[int, cp_model.IntVar] = {}
        self.slot_var: dict[int, cp_model.IntVar] = {}
        self.room_var: dict[int, cp_model.IntVar] = {}
        self.flat_time_var: dict[int, cp_model.IntVar] = {}
        self.room_time_var: dict[int, cp_model.IntVar] = {}
        self.loc_var: dict[int, cp_model.IntVar] = {}

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

            # loc_var[s] = loc_id ucionice dodeljene sesiji s; koriste ga
            # pravila vezana za lokacije (grupe i nastavnici)
            self.loc_var[s] = self.model.NewIntVar(0, max_loc, f"loc_{s}")
            self.model.AddElement(
                self.room_var[s], locations_of_classrooms, self.loc_var[s]
            )

    def create_hard_constraints(self):
        """
        Hard constraint 1: Nikoje 2 sesije ne mogu biti u istoj učionici u datom satu-danu
        Hard constraint 2: Nikoje 2 sesije za istu grupu tj. tok ne mogu biti u istom trenutku
        Npr. Tok A informatika ne može imati 2 različita predavanja u utorak u 10č
        (zajednicka sesija ulazi u ogranicenje svake grupe koja je pohadja)
        Hard constraint 3: Ucionica mora imati racunare ako sesija to zahteva.
        Hard constraint 4: Nastavnik ne moze drzati 2 sesije u istom trenutku
        """
        if not self.sessions:
            return

        # 1) Sve vrednosti room-time moraju biti medjusobno razlicite
        self.model.AddAllDifferent(list(self.room_time_var.values()))

        # 2) Jedna grupa ne moze imati 2 razlicita predavanja u isto vreme
        # uzimamo sve sesije jedne grupe i trazimo da flat_time budu razlicite
        groups = defaultdict(list)
        for s, session in enumerate(self.sessions):
            for group_id in session.group_ids:
                groups[group_id].append(s)

        for group_id, session_indices in groups.items():
            self.model.AddAllDifferent([self.flat_time_var[s] for s in session_indices])

        # 3) dozvoljene ucionice po sesiji: samo racunari
        for s, session in enumerate(self.sessions):
            allowed = [
                i for i, room in enumerate(self.classrooms)
                if not session.needs_computers or room.has_computers
            ]
            if not allowed:
                raise ValueError(
                    f"No eligible room for session '{session.id}' "
                    f"(size={session.size}, needs_computers={session.needs_computers})"
                )
            if len(allowed) < len(self.classrooms):
                self.model.AddAllowedAssignments(
                    [self.room_var[s]],
                    [[idx] for idx in allowed],
                )

        # 4) nastavnik ne moze drzati 2 sesije u isto vreme
        # (isti princip kao za grupe, AllDifferent nad flat_time)
        for teacher_id, session_indices in self.teacher_sessions.items():
            if len(session_indices) > 1:
                self.model.AddAllDifferent(
                    [self.flat_time_var[s] for s in session_indices]
                )

    def apply_rules(self):
        """Pokreni sve rule plugin-ove koji su uključeni u konfiguraciji."""
        self.penalty_vars: list[tuple[int, cp_model.IntVar]] = []

        rule_configs = dict(self.scheduling_input.rules)
        if self.staff_input is not None:
            rule_configs.update(self.staff_input.rules)

        for rule_name, config in rule_configs.items():
            if not config.enabled:
                continue
            rule_class = RULE_REGISTRY.get(rule_name)
            if rule_class is None:
                raise ValueError(f"Unknown rule: '{rule_name}'")
            rule = rule_class(
                enabled=config.enabled, penalty=config.penalty, **config.params
            )
            violations = rule.apply(self)
            for v in violations:
                self.penalty_vars.append((config.penalty, v))

        if self.penalty_vars:
            self.model.Minimize(
                sum(weight * var for weight, var in self.penalty_vars)
            )

    def solve(self, callback: cp_model.CpSolverSolutionCallback | None = None):
        """Callback (ako je zadat) prati poboljsanja funkcije cilja tokom pretrage."""
        if callback is None:
            return self.solver.Solve(self.model)
        return self.solver.Solve(self.model, callback)

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
