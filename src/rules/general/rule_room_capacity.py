"""Kapacitet ucionice, po pravilu kao meko ogranicenje.

Sesija sme da dobije ucionicu u koju svi njeni slusaoci ne staju; kaznjava
se samo prekoracenje, i to brojem studenata koji ostaju bez mesta:

cost[s] = max(0, size[s] - capacity[room[s]])

Zato je kazna nula kad god raspored nikoga ne ostavlja bez mesta, pa se
sabirak lako drzi malim u odnosu na ostala meka pravila.

Tvrda varijanta (penalty == 0) svodi se na klasican kapacitet: sesija sme
samo u ucionice u koje cela kohorta staje.
"""

from ortools.sat.python import cp_model
from src.rules.base import SchedulingRule
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.algo.cp_solver import SimpleCPSolver


class RoomCapacityRule(SchedulingRule):

    def apply(self, solver: "SimpleCPSolver") -> list[cp_model.IntVar]:
        if not solver.sessions or not solver.classrooms:
            return []

        capacities = [room.capacity for room in solver.classrooms]
        overflow_vars: list[cp_model.IntVar] = []

        for s, session in enumerate(solver.sessions):
            if session.size <= 0:
                continue

            overflows = [max(0, session.size - cap) for cap in capacities]
            if not any(overflows):
                continue  # sesija staje u svaku ucionicu

            if self.is_hard:
                fitting = [i for i, over in enumerate(overflows) if over == 0]
                if not fitting:
                    raise ValueError(
                        f"No room fits session '{session.id}' "
                        f"(size={session.size}, largest capacity="
                        f"{max(capacities)})"
                    )
                solver.model.AddAllowedAssignments(
                    [solver.room_var[s]], [[i] for i in fitting]
                )
                continue

            overflow = solver.model.NewIntVar(
                0, max(overflows), f"room_overflow_{s}"
            )
            solver.model.AddElement(solver.room_var[s], overflows, overflow)
            overflow_vars.append(overflow)

        return overflow_vars
