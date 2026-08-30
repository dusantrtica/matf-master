"""Meko pravilo: veće sesije preferiraju veće učionice.

Ne sužava dopustiv skup — sesija sme u bilo koju učionicu koja zadovoljava
tvrda ograničenja (računari). Cena raste sa session.size, pa zajednička
predavanja jače vuku ka većim salama.

cost[s] = size[s] * (max_capacity - capacity[room[s]])
"""

from ortools.sat.python import cp_model
from src.rules.base import SchedulingRule
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.algo.cp_solver import SimpleCPSolver


class PreferLargerRoomsForLargerSessionsRule(SchedulingRule):

    def apply(self, solver: "SimpleCPSolver") -> list[cp_model.IntVar]:
        if not solver.sessions or not solver.classrooms:
            return []

        capacities = [c.capacity for c in solver.classrooms]
        max_capacity = max(capacities)
        cost_vars: list[cp_model.IntVar] = []

        for s, session in enumerate(solver.sessions):
            costs = [
                session.size * (max_capacity - cap) for cap in capacities
            ]
            cost_var = solver.model.NewIntVar(
                min(costs), max(costs), f"room_size_cost_{s}"
            )
            solver.model.AddElement(solver.room_var[s], costs, cost_var)
            cost_vars.append(cost_var)

        # Uvek meko: penalty 0 u konfiguraciji ne menja cilj (0 * cost).
        # Hard varijanta (sve sesije u najvecoj sali) nema smisla.
        return cost_vars
