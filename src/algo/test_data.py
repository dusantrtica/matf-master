import os
import pdb
import sys
import pytest
from functional import seq
from src.algo.data import (
    Group,
    Session,
    load_input,
    split_students_into_groups,
    get_eligible_rooms,
)
from src.algo.model import Settings, StudentsEnrolled, Classroom

mock_settings = Settings(
    **{
        "working_days": ["Ponedeljak", "Utorak", "Sreda", "Četvrtak", "Petak"],
        "start_hour": 8,
        "end_hour": 20,
        "duration": 1,
    }
)


def test_parse_sample_input():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input.json")

    result = load_input(path)
    assert result is not None

    assert result.settings == mock_settings

    assert result.locations[0].id == 1
    assert result.locations[0].name == "Studentski trg"


def test_split_students_into_groups():
    # Arrange
    students_enrollment = [
        StudentsEnrolled(**{"depId": 1, "semester": 1, "count": 90}),
        StudentsEnrolled(**{"depId": 2, "semester": 1, "count": 100}),
    ]
    group_size = 30

    # act
    groups = split_students_into_groups(students_enrollment, group_size)

    # assert
    assert groups == [
        Group(f"1_1_0", 1, 30, 1),
        Group(f"1_1_1", 1, 30, 1),
        Group(f"1_1_2", 1, 30, 1),
        Group(f"2_1_0", 1, 25, 1),
        Group(f"2_1_1", 1, 25, 1),
        Group(f"2_1_2", 1, 25, 1),
        Group(f"2_1_3", 1, 25, 1),
    ]


def test_print_group():
    from src.algo.data import print_group, Group
    from src.algo.model import Department

    # Arrange
    departments = [
        Department(id=1, name="Profesor Matematike i Računarstva"),
    ]
    group = Group(id="1_1_1", dep_id=1, count=30, semester=1)

    assert (
        print_group(group, departments) == "Profesor Matematike i Računarstva, grupa B"
    )


def test_courses_for_department():
    from src.algo.model import Course, Quota

    quota = Quota(2, 3)
    # Arrange
    courses = [
        Course(
            id=1,
            name="Course 1",
            semester=1,
            dep_id=10,
            quota=quota,
            needsComputers=False,
        ),
        Course(
            id=2,
            name="Course 2",
            semester=1,
            dep_id=20,
            quota=quota,
            needsComputers=False,
        ),
        Course(
            id=3,
            name="Course 3",
            semester=1,
            dep_id=10,
            quota=quota,
            needsComputers=False,
        ),
    ]
    # The function should filter only courses with depId = 10
    from src.algo.data import courses_for_department

    result = list(courses_for_department(courses, 10))

    # Assert
    assert len(result) == 2
    assert all(course.dep_id == 10 for course in result)
    ids = [course.id for course in result]
    assert set(ids) == {1, 3}


def test_generate_session_id():
    from src.algo.data import generate_session_id

    group_id = 5
    department_id = 2
    course_id = 17
    course_type = "p"

    session_id = generate_session_id(group_id, department_id, course_id, course_type)

    assert session_id == "5_2_17_p"


def test_department_by_id():
    from src.algo.model import Department
    from src.algo.data import department_by_id

    # Arrange
    departments = [
        Department(id=1, name="Teorijska Matematika"),
        Department(id=2, name="Profesor Matematike"),
        Department(id=3, name="Informatika"),
    ]

    # Act
    result = department_by_id(departments, 2)

    # Assert
    assert result is not None
    assert result.id == 2
    assert result.name == "Profesor Matematike"

    # Test for missing id
    missing = department_by_id(departments, 99)
    assert missing is None


def test_get_eligible_rooms_when_session_requires_computers():
    # Arrange
    classrooms = [
        Classroom(**{"id": 1, "name": "Ucionica 1", "has_computers": True, "locId": 1}),
        Classroom(
            **{"id": 2, "name": "Ucionica 1", "has_computers": False, "locId": 1}
        ),
        Classroom(**{"id": 3, "name": "Ucionica 1", "has_computers": True, "locId": 1}),
        Classroom(
            **{"id": 4, "name": "Ucionica 1", "has_computers": False, "locId": 1}
        ),
    ]

    session = Session(
        id="",
        group_id="",
        department_id="",
        course_id="",
        needs_computers=True,
        session_type="",
    )

    # Act
    eligible_room_ids = get_eligible_rooms(session, classrooms)

    # Assert
    assert eligible_room_ids == [1, 3]


def test_get_eligible_rooms_when_session_does_not_require_computers():
    # Arrange
    classrooms = [
        Classroom(**{"id": 1, "name": "Ucionica 1", "has_computers": True, "locId": 1}),
        Classroom(
            **{"id": 2, "name": "Ucionica 1", "has_computers": False, "locId": 1}
        ),
        Classroom(**{"id": 3, "name": "Ucionica 1", "has_computers": True, "locId": 1}),
        Classroom(
            **{"id": 4, "name": "Ucionica 1", "has_computers": False, "locId": 1}
        ),
    ]

    session = Session(
        id="",
        group_id="",
        department_id="",
        course_id="",
        needs_computers=False,
        session_type="",
    )

    # Act
    eligible_room_ids = get_eligible_rooms(session, classrooms)

    # Assert
    assert eligible_room_ids == [1, 2, 3, 4]


def test_course_sessions():
    from src.algo.data import (
        course_sessions,
        Session,
        generate_session_id,
    )
    from src.algo.model import Course, Quota

    # Arrange
    quota = Quota(theory=2, practice=3)
    course = Course(
        id=10,
        name="Test Course",
        semester=1,
        dep_id=22,
        quota=quota,
        needsComputers=True,
    )
    group_id = "100"

    # Act
    sessions = list(course_sessions(course, group_id))

    # Assert
    # Ukupno 5 sesija, 2 za predavanja t
    assert len(sessions) == 5

    # Check the types and counts
    theory_sessions = [s for s in sessions if s.session_type == "theory"]
    practice_sessions = [s for s in sessions if s.session_type == "practice"]
    assert len(theory_sessions) == 2
    assert len(practice_sessions) == 3

    # IDs should have the correct format
    expected_theory_id = generate_session_id(group_id, course.dep_id, course.id, "t")
    expected_practice_id = generate_session_id(group_id, course.dep_id, course.id, "p")
    for s in theory_sessions:
        assert s.id == expected_theory_id
        assert s.group_id == group_id
        assert s.department_id == course.dep_id
        assert s.course_id == course.id
        assert s.needs_computers == True
        assert s.session_type == "theory"
    for s in practice_sessions:
        assert s.id == expected_practice_id
        assert s.group_id == group_id
        assert s.department_id == course.dep_id
        assert s.course_id == course.id
        assert s.needs_computers == True
        assert s.session_type == "practice"


def test_generate_sessions():
    from src.algo.model import (
        SchedulingInput,
        StudentsEnrolled,
        Quota,
        Course,
        Quota,
        Department,
    )

    from src.algo.data import (
        generate_sessions,
    )

    # Arrange
    departments = [
        Department(id=10, name="Informatika"),
        Department(id=20, name="Teorijska Matematika"),
    ]
    students_enrolled = [
        StudentsEnrolled(dep_id=10, count=90, semester=1),
        StudentsEnrolled(dep_id=20, count=100, semester=1),
    ]
    courses = [
        Course(
            id=101,
            name="Uvod u Programiranje",
            semester=1,
            dep_id=10,
            quota=Quota(theory=1, practice=2),
            need_computers=True,
        ),
        Course(
            id=103,
            name="Analiza 1",
            semester=1,
            dep_id=20,
            quota=Quota(theory=2, practice=3),
            need_computers=False,
        ),
    ]
    scheduling_input = SchedulingInput(
        students_enrolled=students_enrolled,
        courses=courses,
        departments=departments,
        locations=[],
        classrooms=[],
        settings=mock_settings,
    )

    # Act
    result = list(generate_sessions(scheduling_input, group_size=50))
    assert result[0].id == "10_1_0_10_101_t"
    assert result[1].id == "10_1_0_10_101_p"
    assert result[2].id == "10_1_0_10_101_p"

    assert result[3].id == "10_1_1_10_101_t"
    assert result[4].id == "10_1_1_10_101_p"
    assert result[5].id == "10_1_1_10_101_p"

    assert result[6].id == "20_1_0_20_103_t"
    assert result[7].id == "20_1_0_20_103_t"
    assert result[8].id == "20_1_0_20_103_p"
    assert result[9].id == "20_1_0_20_103_p"
    assert result[10].id == "20_1_0_20_103_p"

    assert result[11].id == "20_1_1_20_103_t"
    assert result[12].id == "20_1_1_20_103_t"
    assert result[13].id == "20_1_1_20_103_p"
    assert result[14].id == "20_1_1_20_103_p"
    assert result[15].id == "20_1_1_20_103_p"


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
