import sys
from collections import defaultdict

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


@pytest.fixture
def scheduling_input():
    """Mali, izvodljiv ulaz: jedna grupa (30 studenata), jedan dan, dovoljno
    sati i ucionica da se 3 sesije mogu rasporediti bez procepa.
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
            Classroom(**{"id": 1, "name": "840", "locId": 1, "has_computers": False}),
            Classroom(**{"id": 2, "name": "704", "locId": 1, "has_computers": False}),
            Classroom(**{"id": 3, "name": "841", "locId": 1, "has_computers": False}),
        ],
        courses=[
            Course(
                **{
                    "id": 1,
                    "name": "Analiza 1",
                    "semester": 1,
                    "depId": 1,
                    "quota": Quota(**{"theory": 2, "practice": 1}),
                    "needsComputers": 0,
                }
            ),
        ],
        locations=[],
        departments=[],
        students_enrolled=[
            StudentsEnrolled(**{"depId": 1, "semester": 1, "count": 30}),
        ],
        rules={
            "noGapsInSchedule": RuleConfig(enabled=True, penalty=5),
        },
    )


def _interior_gaps(variables, sessions):
    """Broj slobodnih sati koji se nalaze izmedju dva zauzeta sata u istom
    danu za istu grupu (unutrasnji procepi).
    """
    occupied: dict[tuple, list[int]] = defaultdict(list)
    for v, session in zip(variables, sessions):
        occupied[(session.group_id, v["day"])].append(v["hour"])

    total = 0
    for hours in occupied.values():
        span = max(hours) - min(hours) + 1
        total += span - len(hours)
    return total


def test_no_gaps_rule_minimizes_gaps(scheduling_input):
    solver = SimpleCPSolver(scheduling_input, log_progress=False)
    status = solver.solve()

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    variables = solver.get_solution_variables()
    sessions = solver.sessions
    assert len(sessions) == 3

    assert _interior_gaps(variables, sessions) == 0


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
