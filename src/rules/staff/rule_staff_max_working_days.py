"""Rule: maksimalan broj radnih dana nastavnika u nedelji

Iz ulaznog fajla profesora: literali poput -aleksandra.marinkovic_5day
znace da nastavnik ne sme drzati nastavu svih 5 radnih dana. Ovde je to
uopsteno: svaki nastavnik radi najvise maxDays dana nedeljno, a pojedinacni
nastavnik moze imati svoj limit preko polja maxWorkingDays.

Hard (penalty == 0): sum(radni dani) <= max_days.
Soft (penalty > 0): minimizuje se broj dana preko limita.
"""

from ortools.sat.python import cp_model
from src.rules.base import SchedulingRule
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.algo.cp_solver import SimpleCPSolver

DEFAULT_MAX_DAYS = 4


class StaffMaxWorkingDaysRule(SchedulingRule):

    def __init__(self, enabled: bool = True, penalty: int = 0, **kwargs):
        super().__init__(enabled=enabled, penalty=penalty, **kwargs)
        self.max_days = kwargs.get("maxDays", DEFAULT_MAX_DAYS)

    def apply(self, solver: "SimpleCPSolver") -> list[cp_model.IntVar]:
        D = len(solver.settings.working_days)
        max_days_by_teacher = {
            t.id: t.max_working_days
            for t in solver.teachers
            if t.max_working_days is not None
        }

        violations: list[cp_model.IntVar] = []
        for teacher_id, session_indices in solver.teacher_sessions.items():
            limit = max_days_by_teacher.get(teacher_id, self.max_days)
            day_used = self._build_day_used(solver, teacher_id, session_indices, D)
            worked_days = sum(day_used)

            if self.is_hard:
                solver.model.Add(worked_days <= limit)
            else:
                # broj dana preko limita, solver ga minimizuje
                excess = solver.model.NewIntVar(
                    0, D, f"staff_days_excess_{teacher_id}"
                )
                solver.model.Add(excess >= worked_days - limit)
                violations.append(excess)

        return violations

    def _build_day_used(
        self,
        solver: "SimpleCPSolver",
        teacher_id: int,
        session_indices: list[int],
        D: int,
    ) -> list[cp_model.IntVar]:
        """day_used[d] == 1 ako nastavnik ima bar jednu sesiju u danu d."""
        day_used: list[cp_model.IntVar] = []
        for d in range(D):
            lits: list[cp_model.IntVar] = []
            for s in session_indices:
                lit = solver.model.NewBoolVar(f"t{teacher_id}_s{s}_day{d}")
                solver.model.Add(solver.day_var[s] == d).OnlyEnforceIf(lit)
                solver.model.Add(solver.day_var[s] != d).OnlyEnforceIf(lit.Not())
                lits.append(lit)
            used = solver.model.NewBoolVar(f"t{teacher_id}_used_day{d}")
            solver.model.AddMaxEquality(used, lits)  # OR preko sesija
            day_used.append(used)
        return day_used
