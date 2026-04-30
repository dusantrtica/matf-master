import math
from collections import defaultdict
from ortools.sat.python import cp_model
from typing import List
from src.algo.data import Session, generate_sessions, GROUP_SIZE
from src.algo.model import (
    SchedulingInput,
    Settings,
    Course,
)

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
        self.init_input(scheduling_input)
        
        self.create_assignment_variables()
        self.create_hard_constraints()
        self.set_objective()

    def init_input(self, scheduling_input: SchedulingInput):
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

    def set_objective(self):
        """
        Minimizovati najkasniji sat na danu.
        Ovo motiviše solver da rasporedi sesije na različite dane
        umesto da ih skupi u jedan dan do poslednjeg sata.
        Takođe, dodajemo izračunatu donju granicu: grupa sa najviše sesija
        treba da ima najmanje ceil(num_sessions / num_days) satnih slotova, tako da
        max_slot >= ceil(max_group_sessions / D) - 1. Ovo pomaže solveru
        da dostigne optimalnost mnogo brže, al nije  neophodno za dobijanje optimalnog rešenja.
        """
        if not self.sessions:
            return

        D = len(self.settings.working_days)
        H = len(self.working_hours)

        # Racunamo lower bound, da bismo pomogli solveru da pre dostigne optimalnost,
        # inače nije neophodno.
        groups = defaultdict(int)
        for session in self.sessions:
            groups[session.group_id] += 1
        max_group_sessions = max(groups.values()) if groups else 0
        # npr ako imamo 5 sesija i 3 dana, lower_bound je 1, tj. moramo imati bar 1 sat u toku dana.
        lower_bound = math.ceil(max_group_sessions / D) - 1 if D > 0 else 0

        # max slot mora je manji od broja sati u toku dana, a
        # želimo i da ga minimizujemo tako da se predavanja što pre završe u toku dana.
        # implicitno, ako minimizujemo max_slot, minimizujemo i broj sati u toku dana.
        # i to ce terati solver da rasporedi sesije tokom vise dana, ali tako da se zavrsavju sto pre.
        self.max_slot = self.model.NewIntVar(lower_bound, H - 1, "max_slot")
        for s in range(len(self.sessions)):
            self.model.Add(self.max_slot >= self.slot_var[s])
        self.model.Minimize(self.max_slot)

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
