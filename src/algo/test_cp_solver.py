from ortools.sat.python import cp_model
from src.algo.cp_solver import SimpleCPSolver
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


@pytest.fixture
def sessions(scheduling_input):
    """Build 8 sessions (4 theory + 4 practice) for a single student group."""
    course = scheduling_input.courses[0]
    result = []
    for i in range(course.quota.theory):
        result.append(
            Session(f"t_{i}", "grp_1", course.dep_id, course.id,
                    course.needs_computers, "theory")
        )
    for i in range(course.quota.practice):
        result.append(
            Session(f"p_{i}", "grp_1", course.dep_id, course.id,
                    course.needs_computers, "practice")
        )
    return result


def test_cp_solver_init_data(scheduling_input):
    solver = SimpleCPSolver(scheduling_input, log_progress=False)
    assert solver.settings == scheduling_input.settings
    assert solver.classrooms == scheduling_input.classrooms
    assert solver.courses == scheduling_input.courses
    assert solver.departments == scheduling_input.departments
    assert solver.students_enrolled == scheduling_input.students_enrolled
    assert solver.working_hours == [8, 9, 10, 11, 12, 13]


def test_cp_solver_basic_constraint(scheduling_input, sessions):
    solver = SimpleCPSolver(scheduling_input, log_progress=False)
    status = solver.solve()

    assert status == cp_model.OPTIMAL
    variables = solver.get_solution_variables()
 
    # Broj varijabli mora da odgovara broju sesija generisanih od strane solvera.    
    generated_sessions = solver.sessions
    assert len(variables) == len(generated_sessions)

    # Proveriti da nikoje 2 sesije ne deli istu ucionicu u istom vremenskom trenutku
    room_times = set()
    for v in variables:
        key = (v["day"], v["hour"], v["room"])
        assert key not in room_times, f"Room-time collision: {key}"
        room_times.add(key)

    # Proveriti da nikoje 2 sesije za istu grupu ne deli isti vremenski trenutak
    group_times = set()
    for v, session in zip(variables, generated_sessions):
        key = (session.group_id, v["day"], v["hour"])
        assert key not in group_times, f"Group-time collision: {key}"
        group_times.add(key)

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
