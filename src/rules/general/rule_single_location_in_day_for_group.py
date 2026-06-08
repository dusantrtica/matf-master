from src.rules.base import SchedulingRule
from ortools.sat.python import cp_model
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.algo.cp_solver import SimpleCPSolver


class SingleLocationInDayForGroupRule(SchedulingRule):

    def apply(self, solver: "SimpleCPSolver") -> list[cp_model.IntVar]:
        """
        Svaka grupa u danu ne sme menjati lokaciju.
        Sve sesije jedne grupe u istom danu su na istoj lokaciji
        (Trg, Sv. Nikole ili Jagiceva).
        """
        self.locations_of_classrooms = [c.loc_id for c in solver.classrooms]
        max_loc = max(self.locations_of_classrooms)

        # group_id -> globalni indeksi sesija te grupe
        group_session_indices: dict[int, list[int]] = defaultdict(list)
        for s, session in enumerate(solver.sessions):
            group_session_indices[session.group_id].append(s)

        # loc[s] = loc_id ucionice dodeljene sesiji s
        loc: dict[int, cp_model.IntVar] = {}
        for s in range(len(solver.sessions)):
            loc[s] = solver.model.NewIntVar(0, max_loc, f"loc_{s}")
            solver.model.AddElement(solver.room_var[s], self.locations_of_classrooms, loc[s])

        return self._add_hard(solver, loc, group_session_indices, max_loc)

    def _add_hard(
        self,
        solver: "SimpleCPSolver",
        loc: dict[int, cp_model.IntVar],
        group_session_indices: dict[int, list[int]],
        max_loc: int,
    ) -> list[cp_model.IntVar]:
        D = len(solver.settings.working_days)

        # lokacija grupe g u danu d (d je indeks 0..D-1)
        group_day_loc: dict[tuple[int, int], cp_model.IntVar] = {}
        for g in group_session_indices:
            for d in range(D):
                group_day_loc[g, d] = solver.model.NewIntVar(
                    0, max_loc, f"group_day_loc_{g}_{d}"
                )

        for g, indices in group_session_indices.items():
            day_locs = [group_day_loc[g, d] for d in range(D)]
            for s in indices:
                # loc[s] == group_day_loc[g][day_var[s]]
                solver.model.AddElement(solver.day_var[s], day_locs, loc[s])

        return []
