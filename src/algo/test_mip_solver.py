from ortools.linear_solver import pywraplp
from src.algo.mip_solver import SimpleMIPSolver
from src.algo.data import Session

import pytest
import sys
from src.algo.model import (
    Classroom,
    SchedulingInput,
    Settings,
    Course,
    Quota,
)


@pytest.fixture
def scheduling_input():
    return SchedulingInput(
        settings=Settings(
            **{
                "working_days": ["Ponedeljak", "Utorak", "Sreda"],
                "start_hour": 8,
                "end_hour": 14,
            }
        ),
        classrooms=[
            Classroom(**{"id": 1, "name": "840", "locId": 1, "has_computers": False}),
            Classroom(**{"id": 2, "name": "704", "locId": 1, "has_computers": True}),
            Classroom(**{"id": 3, "name": "841", "locId": 1, "has_computers": False}),
        ],
        courses=[
            Course(
                **{
                    "id": 1,
                    "name": "Analiza 1",
                    "semester": 1,
                    "depId": 1,
                    "quota": Quota(**{"theory": 4, "practice": 4}),
                    "needsComputers": 0,
                }
            ),
        ],
        locations=[],
        departments=[],
        students_enrolled=[],
    )


def test_mip_solver_init_data(scheduling_input):
    solver = SimpleMIPSolver(scheduling_input)
    assert solver.settings == scheduling_input.settings
    assert solver.classrooms == scheduling_input.classrooms
    assert solver.courses == scheduling_input.courses
    assert solver.departments == scheduling_input.departments
    assert solver.students_enrolled == scheduling_input.students_enrolled
    assert solver.working_hours == [8, 9, 10, 11, 12, 13]


def test_mip_solver_basic_constraint(scheduling_input):
    course = scheduling_input.courses[0]
    sessions = []
    for i in range(course.quota.theory):
        sessions.append(
            Session(f"t_{i}", "grp_1", course.dep_id, course.id,
                    course.needs_computers, "theory")
        )
    for i in range(course.quota.practice):
        sessions.append(
            Session(f"p_{i}", "grp_1", course.dep_id, course.id,
                    course.needs_computers, "practice")
        )

    solver = SimpleMIPSolver(scheduling_input)
    solver.sessions = sessions
    solver.x = {}
    inner_solver = pywraplp.Solver.CreateSolver("SCIP")
    inner_solver.SetTimeLimit(30000)
    solver.solver = inner_solver
    solver.create_assignment_variables()
    solver.create_hard_constraints()
    solver.set_objective()

    status = solver.solve()
    assert status == pywraplp.Solver.OPTIMAL

    variables = solver.get_solution_variables()
    assert len(variables) == 8

    room_times = set()
    for v in variables:
        key = (v["day"], v["hour"], v["room"])
        assert key not in room_times, f"Room-time collision: {key}"
        room_times.add(key)

    group_times = set()
    for v in variables:
        key = ("grp_1", v["day"], v["hour"])
        assert key not in group_times, f"Group-time collision: {key}"
        group_times.add(key)


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
