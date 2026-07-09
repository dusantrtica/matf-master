"""Rule: nastavnik ne menja lokaciju u toku jednog dana

Sve sesije jednog nastavnika u istom danu moraju biti na istoj lokaciji
(Trg, Sv. Nikole ili Jagiceva). Bez ovoga bi nastavnik mogao imati dva
uzastopna casa na razlicitim lokacijama, sto je fizicki neizvodljivo.

Pravilo je hard ogranicenje (analogno SingleLocationInDayForGroupRule
za grupe).
"""

from ortools.sat.python import cp_model
from src.rules.base import SchedulingRule
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.algo.cp_solver import SimpleCPSolver


class StaffSingleLocationInDayRule(SchedulingRule):

    def apply(self, solver: "SimpleCPSolver") -> list[cp_model.IntVar]:
        D = len(solver.settings.working_days)
        max_loc = max(c.loc_id for c in solver.classrooms)

        for teacher_id, session_indices in solver.teacher_sessions.items():
            # nastavnik sa jednom sesijom ne moze promeniti lokaciju
            if len(session_indices) < 2:
                continue

            # lokacija nastavnika t u danu d (d je indeks 0..D-1)
            day_locs = [
                solver.model.NewIntVar(0, max_loc, f"teacher_day_loc_{teacher_id}_{d}")
                for d in range(D)
            ]
            for s in session_indices:
                # loc_var[s] == day_locs[day_var[s]]
                solver.model.AddElement(solver.day_var[s], day_locs, solver.loc_var[s])

        return []
