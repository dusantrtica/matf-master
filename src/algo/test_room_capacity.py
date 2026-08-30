import sys

import pytest
from ortools.sat.python import cp_model

from src.algo.cp_solver import SimpleCPSolver
from src.algo.model import (
    Classroom,
    Course,
    Quota,
    RuleConfig,
    SchedulingInput,
    Settings,
    StudentsEnrolled,
)


def _input(rules: dict, largest_capacity: int = 40) -> SchedulingInput:
    """Jedna grupa od 30 studenata i tri ucionice razlicitog kapaciteta.

    Samo najveca ucionica prima celu grupu; `largest_capacity` manji od 30
    znaci da nijedna ucionica ne prima grupu u celosti.
    """
    return SchedulingInput(
        settings=Settings(
            **{
                "working_days": ["Ponedeljak"],
                "start_hour": 8,
                "end_hour": 14,
            }
        ),
        classrooms=[
            Classroom(**{"id": 1, "name": "mala", "locId": 1,
                         "has_computers": False, "capacity": 10}),
            Classroom(**{"id": 2, "name": "srednja", "locId": 1,
                         "has_computers": False, "capacity": 20}),
            Classroom(**{"id": 3, "name": "velika", "locId": 1,
                         "has_computers": False, "capacity": largest_capacity}),
        ],
        courses=[
            Course(
                **{
                    "id": 1,
                    "name": "Analiza 1",
                    "semester": 1,
                    "trackId": 1,
                    "quota": Quota(**{"theory": 1, "practice": 0}),
                    "needsComputers": 0,
                }
            ),
        ],
        locations=[],
        tracks=[],
        students_enrolled=[
            StudentsEnrolled(**{"trackId": 1, "semester": 1, "count": 30}),
        ],
        rules=rules,
    )


def _room_capacity(solver, variables):
    return [
        solver.classrooms[v["room"]].capacity for v in variables
    ]


def test_soft_rule_prefers_room_that_fits():
    scheduling_input = _input({"roomCapacity": RuleConfig(enabled=True, penalty=1)})
    solver = SimpleCPSolver(scheduling_input, log_progress=False)
    status = solver.solve()

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    variables = solver.get_solution_variables()
    assert _room_capacity(solver, variables) == [40]


def test_soft_rule_allows_overflow_when_nothing_fits():
    """Nijedna ucionica ne prima 30 studenata: raspored ipak postoji, a
    rezavac bira ucionicu sa najmanjim prekoracenjem."""
    scheduling_input = _input(
        {"roomCapacity": RuleConfig(enabled=True, penalty=1)}, largest_capacity=25
    )
    solver = SimpleCPSolver(scheduling_input, log_progress=False)
    status = solver.solve()

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    variables = solver.get_solution_variables()
    assert _room_capacity(solver, variables) == [25]


def test_hard_rule_forbids_rooms_that_do_not_fit():
    scheduling_input = _input({"roomCapacity": RuleConfig(enabled=True, penalty=0)})
    solver = SimpleCPSolver(scheduling_input, log_progress=False)
    status = solver.solve()

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    variables = solver.get_solution_variables()
    assert _room_capacity(solver, variables) == [40]


def test_hard_rule_infeasible_when_nothing_fits():
    scheduling_input = _input(
        {"roomCapacity": RuleConfig(enabled=True, penalty=0)}, largest_capacity=25
    )
    with pytest.raises(ValueError, match="No room fits session"):
        SimpleCPSolver(scheduling_input, log_progress=False)


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
