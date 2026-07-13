import sys
from collections import defaultdict

import pytest
from ortools.sat.python import cp_model

from src.algo.cp_solver import SimpleCPSolver
from src.algo.data import generate_sessions, GROUP_SIZE
from src.algo.model import (
    Classroom,
    Course,
    GroupDef,
    Quota,
    RuleConfig,
    SchedulingInput,
    Settings,
    StaffInput,
    StudentsEnrolled,
    Teacher,
    TeachingAssignment,
)


@pytest.fixture
def scheduling_input():
    """Dva odseka sa po jednom grupom; nastavnik 1 drzi teoriju oba kursa
    (4 sesije preko 2 grupe), nastavnik 2 drzi vezbe kursa 1.
    """
    return SchedulingInput(
        settings=Settings(
            **{
                "working_days": ["Ponedeljak", "Utorak"],
                "start_hour": 8,
                "end_hour": 14,
            }
        ),
        classrooms=[
            Classroom(**{"id": 1, "name": "840", "locId": 1, "has_computers": False}),
            Classroom(**{"id": 2, "name": "704", "locId": 1, "has_computers": False}),
            Classroom(**{"id": 3, "name": "JAG1", "locId": 2, "has_computers": False}),
            Classroom(**{"id": 4, "name": "JAG2", "locId": 2, "has_computers": False}),
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
            Course(
                **{
                    "id": 2,
                    "name": "Uvod u algoritme",
                    "semester": 1,
                    "depId": 2,
                    "quota": Quota(**{"theory": 2, "practice": 0}),
                    "needsComputers": 0,
                }
            ),
        ],
        locations=[],
        departments=[],
        students_enrolled=[
            StudentsEnrolled(**{"depId": 1, "semester": 1, "count": 30}),
            StudentsEnrolled(**{"depId": 2, "semester": 1, "count": 30}),
        ],
        rules={},
    )


@pytest.fixture
def staff_input():
    return StaffInput(
        teachers=[
            Teacher(id=1, name="predrag.janicic", max_working_days=1),
            Teacher(id=2, name="milan.kocic"),
        ],
        assignments=[
            TeachingAssignment(teacher_id=1, course_id=1, session_type="theory"),
            TeachingAssignment(teacher_id=1, course_id=2, session_type="theory"),
            TeachingAssignment(teacher_id=2, course_id=1, session_type="practice"),
        ],
        rules={
            "staffMaxWorkingDays": RuleConfig(
                enabled=True, penalty=0, params={"maxDays": 2}
            ),
            "staffMaxGapHoursPerWeek": RuleConfig(
                enabled=True, penalty=0, params={"maxGapHours": 1}
            ),
            "staffSingleLocationInDay": RuleConfig(enabled=True, penalty=0),
        },
    )


def _teacher_schedule(solver, variables):
    """teacher_id -> lista (day, hour) parova iz resenja."""
    schedule: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for v, session in zip(variables, solver.sessions):
        if session.teacher_id is not None:
            schedule[session.teacher_id].append((v["day"], v["hour"]))
    return schedule


def _weekly_gaps(times):
    """Broj slobodnih sati izmedju prvog i poslednjeg casa po danima."""
    by_day: dict[int, list[int]] = defaultdict(list)
    for day, hour in times:
        by_day[day].append(hour)

    total = 0
    for hours in by_day.values():
        span = max(hours) - min(hours) + 1
        total += span - len(hours)
    return total


def test_teachers_resolved_on_sessions(scheduling_input, staff_input):
    sessions = generate_sessions(scheduling_input, GROUP_SIZE, staff_input)

    by_teacher = defaultdict(list)
    for s in sessions:
        by_teacher[s.teacher_id].append(s)

    # 4 teorijske sesije (2 po kursu) za nastavnika 1, 1 vezba za nastavnika 2
    assert len(by_teacher[1]) == 4
    assert len(by_teacher[2]) == 1
    assert all(s.session_type == "theory" for s in by_teacher[1])
    assert all(s.session_type == "practice" for s in by_teacher[2])


def test_teacher_never_double_booked(scheduling_input, staff_input):
    solver = SimpleCPSolver(scheduling_input, staff_input=staff_input, log_progress=False)
    status = solver.solve()
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    schedule = _teacher_schedule(solver, solver.get_solution_variables())
    for teacher_id, times in schedule.items():
        assert len(times) == len(set(times)), (
            f"Teacher {teacher_id} double-booked: {times}"
        )


def test_teacher_max_working_days_respected(scheduling_input, staff_input):
    solver = SimpleCPSolver(scheduling_input, staff_input=staff_input, log_progress=False)
    status = solver.solve()
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    schedule = _teacher_schedule(solver, solver.get_solution_variables())

    # nastavnik 1 ima licni limit od 1 radnog dana (nadjacava default 2)
    days_teacher_1 = {day for day, _ in schedule[1]}
    assert len(days_teacher_1) <= 1

    # nastavnik 2 koristi podrazumevani limit pravila (2 dana)
    days_teacher_2 = {day for day, _ in schedule[2]}
    assert len(days_teacher_2) <= 2


def test_teacher_weekly_gap_budget_respected(scheduling_input, staff_input):
    solver = SimpleCPSolver(scheduling_input, staff_input=staff_input, log_progress=False)
    status = solver.solve()
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    schedule = _teacher_schedule(solver, solver.get_solution_variables())
    for teacher_id, times in schedule.items():
        assert _weekly_gaps(times) <= 1, (
            f"Teacher {teacher_id} has more than 1 gap hour: {times}"
        )


def test_teacher_single_location_per_day(scheduling_input, staff_input):
    solver = SimpleCPSolver(scheduling_input, staff_input=staff_input, log_progress=False)
    status = solver.solve()
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    variables = solver.get_solution_variables()
    # teacher_id -> day -> skup lokacija na kojima drzi nastavu tog dana
    locations_by_day: dict[int, dict[int, set[int]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for v, session in zip(variables, solver.sessions):
        if session.teacher_id is not None:
            loc_id = scheduling_input.classrooms[v["room"]].loc_id
            locations_by_day[session.teacher_id][v["day"]].add(loc_id)

    for teacher_id, days in locations_by_day.items():
        for day, locs in days.items():
            assert len(locs) == 1, (
                f"Teacher {teacher_id} changes location on day {day}: {locs}"
            )


def test_solver_without_staff_input_unchanged(scheduling_input):
    solver = SimpleCPSolver(scheduling_input, log_progress=False)
    status = solver.solve()
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert all(s.teacher_id is None for s in solver.sessions)


@pytest.fixture
def joint_scheduling_input():
    """Dve eksplicitne grupe; teoriju slusaju zajedno, vezbe odvojeno.
    Samo jedna ucionica ima kapacitet za zajednicku sesiju (55 studenata).
    """
    return SchedulingInput(
        settings=Settings(
            **{
                "working_days": ["Ponedeljak", "Utorak"],
                "start_hour": 8,
                "end_hour": 14,
            }
        ),
        classrooms=[
            Classroom(**{"id": 1, "name": "Mala1", "locId": 1,
                         "has_computers": False, "capacity": 30}),
            Classroom(**{"id": 2, "name": "Mala2", "locId": 1,
                         "has_computers": False, "capacity": 30}),
            Classroom(**{"id": 3, "name": "Amfiteatar", "locId": 1,
                         "has_computers": False, "capacity": 100}),
        ],
        courses=[
            Course(
                **{
                    "id": 1,
                    "name": "Analiza 1",
                    "semester": 1,
                    "depId": 1,
                    "quota": Quota(**{"theory": 2, "practice": 2}),
                    "needsComputers": 0,
                }
            ),
        ],
        locations=[],
        departments=[],
        students_enrolled=[],
        groups=[
            GroupDef(id="ga", dep_id=1, semester=1, count=30),
            GroupDef(id="gb", dep_id=1, semester=1, count=25),
        ],
        rules={},
    )


@pytest.fixture
def joint_staff_input():
    return StaffInput(
        teachers=[Teacher(id=1, name="predrag.janicic")],
        assignments=[
            TeachingAssignment(teacher_id=1, course_id=1, session_type="theory",
                               group_ids=["ga", "gb"]),
        ],
        rules={},
    )


def test_joint_session_solved(joint_scheduling_input, joint_staff_input):
    solver = SimpleCPSolver(
        joint_scheduling_input, staff_input=joint_staff_input, log_progress=False
    )

    # 2 zajednicke teorijske + po 2 vezbe za svaku grupu = 6 sesija
    assert len(solver.sessions) == 6

    status = solver.solve()
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    variables = solver.get_solution_variables()

    # nijedna grupa nema 2 sesije u isto vreme (racunajuci i zajednicke)
    group_times = set()
    for v, session in zip(variables, solver.sessions):
        for group_id in session.group_ids:
            key = (group_id, v["day"], v["hour"])
            assert key not in group_times, f"Group-time collision: {key}"
            group_times.add(key)

    # zajednicka sesija (55 studenata) mora biti u amfiteatru (kapacitet 100)
    for v, session in zip(variables, solver.sessions):
        if len(session.group_ids) > 1:
            room = joint_scheduling_input.classrooms[v["room"]]
            assert room.capacity >= session.size


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
