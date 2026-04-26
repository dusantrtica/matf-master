import math
from collections import defaultdict
from typing import List

from ortools.linear_solver import pywraplp

from src.algo.model import (
    SchedulingInput,
    Settings,
    Course,
    Classroom,
)
from src.algo.data import Session, generate_sessions, GROUP_SIZE


class SimpleMIPSolver:
    """
    Klasa SimpleMIPSolver, koristi MIP (Mixed Integer Programming) pristup
    da napravi raspored nastave.

    Binarna promenljiva x[s, d, h, r] = 1 ako je sesija s rasporedjena
    na dan d, sat h, u ucionicu r.

    Koristi OR-Tools SCIP solver (pywraplp) za resavanje MIP problema.
    """

    def __init__(
        self,
        scheduling_input: SchedulingInput,
        max_time_seconds: float = 30.0,
    ):
        self.solver = pywraplp.Solver.CreateSolver("SCIP")
        if not self.solver:
            raise RuntimeError("SCIP solver not available in OR-Tools")
        self.solver.SetTimeLimit(int(max_time_seconds * 1000))
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

    def _eligible_room_indices(self, session: Session) -> List[int]:
        """Vraca indekse ucionica u kojima sesija moze da se odrzi."""
        indices = []
        for i, room in enumerate(self.classrooms):
            if session.needs_computers and not room.has_computers:
                continue
            indices.append(i)
        return indices

    def create_assignment_variables(self):
        """
        Za svaku sesiju s, kreiramo binarne promenljive x[s][(d, h, r)]
        za svaku dozvoljenu kombinaciju (dan, sat, ucionica).

        Promenljive za nedozvoljene kombinacije (sesija zahteva racunare
        ali ucionica ih nema) se ne kreiraju -- time se implicitno
        postuje ogranicenje da ucionica ima racunare ako sesija zahteva racunare.
        """
        D = len(self.settings.working_days)
        H = len(self.working_hours)
        R = len(self.classrooms)
        
        # Kako cuvamo promenljive?
        # x[s][(d, h, r)] = 1 ako je sesija s rasporedjena na dan d, sat h, u ucionicu r.
        self.x: dict[int, dict[tuple[int, int, int], pywraplp.Variable]] = {}

        for s, session in enumerate(self.sessions):
            self.x[s] = {}
            eligible = self._eligible_room_indices(session)
            for d in range(D):
                for h in range(H):
                    for r in eligible:
                        self.x[s][(d, h, r)] = self.solver.BoolVar(
                            f"x_{s}_{d}_{h}_{r}"
                        )

    def create_hard_constraints(self):
        """
        Hard constraint 1: Svaka sesija mora biti rasporedjena tacno jednom.
           sum_{d,h,r} x[s,d,h,r] = 1, za svako s

        Hard constraint 2: Nikoje 2 sesije ne mogu biti u istoj ucionici
        u isto vreme.
           sum_{s} x[s,d,h,r] <= 1, za svako (d, h, r)

        Hard constraint 3: Nikoje 2 sesije iste grupe ne mogu biti u isto
        vreme.
           sum_{s in grupa, r} x[s,d,h,r] <= 1, za svaku grupu i svako (d, h)
        """
        if not self.sessions:
            return

        D = len(self.settings.working_days)
        H = len(self.working_hours)
        R = len(self.classrooms)
        S = len(self.sessions)

        # 1) Svaka sesija rasporedjena tacno jednom
        for s in range(S):
            self.solver.Add(sum(self.x[s].values()) == 1)

        # 2) Najvise jedna sesija u datoj (dan, sat, ucionica) kombinaciji
        for d in range(D):
            for h in range(H):
                for r in range(R):
                    vars_at_dhr = [
                        self.x[s][(d, h, r)]
                        for s in range(S)
                        if (d, h, r) in self.x[s]
                    ]
                    if len(vars_at_dhr) > 1:
                        self.solver.Add(sum(vars_at_dhr) <= 1)

        # 3) Jedna grupa ne moze imati 2 sesije u isto vreme
        groups = defaultdict(list)
        for s, session in enumerate(self.sessions):
            groups[session.group_id].append(s)

        for group_id, session_indices in groups.items():
            for d in range(D):
                for h in range(H):
                    vars_at_dh = [
                        self.x[s][(d, h, r)]
                        for s in session_indices
                        for r in range(R)
                        if (d, h, r) in self.x[s]
                    ]
                    if len(vars_at_dh) > 1:
                        self.solver.Add(sum(vars_at_dh) <= 1)

    def set_objective(self):
        """
        Minimizujemo max_slot -- najkasniji sat koriscen bilo kog dana.
        Za svaku sesiju s, slot sesije s = sum_{d,h,r} h * x[s,d,h,r],
        pa stavljamo max_slot >= taj izraz.
        """
        if not self.sessions:
            return

        D = len(self.settings.working_days)
        H = len(self.working_hours)

        groups = defaultdict(int)
        for session in self.sessions:
            groups[session.group_id] += 1
        max_group_sessions = max(groups.values()) if groups else 0
        lower_bound = math.ceil(max_group_sessions / D) - 1 if D > 0 else 0

        self.max_slot = self.solver.IntVar(lower_bound, H - 1, "max_slot")

        for s in range(len(self.sessions)):
            self.solver.Add(
                self.max_slot >= sum(
                    h * self.x[s][(d, h, r)]
                    for (d, h, r) in self.x[s]
                )
            )

        self.solver.Minimize(self.max_slot)

    def solve(self):
        status = self.solver.Solve()
        return status

    def get_solution_variables(self):
        """
        Nakon solve(), izvlacimo dan, sat i indeks ucionice za svaku sesiju.
        Vraca isti format kao SimpleCPSolver: {"day": ..., "hour": ..., "room": ...}
        """
        result = []
        for s in range(len(self.sessions)):
            for (d, h, r), var in self.x[s].items():
                if var.solution_value() >= 0.99:
                    result.append({"day": d, "hour": h, "room": r})
                    break
        return result
