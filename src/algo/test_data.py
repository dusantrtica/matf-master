import os
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
        StudentsEnrolled(**{"trackId": 1, "semester": 1, "count": 90}),
        StudentsEnrolled(**{"trackId": 2, "semester": 1, "count": 100}),
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


def test_legacy_department_keys_are_still_accepted():
    """Ulazi napisani pre preimenovanja (`departments`, `depId`) moraju
    da se ucitaju isto kao i oni sa novim nazivima."""
    from pydantic import TypeAdapter
    from src.algo.model import SchedulingInput

    legacy = {
        "settings": {"workingDays": ["Ponedeljak"], "startHour": 8, "endHour": 20},
        "locations": [],
        "classrooms": [],
        "departments": [{"id": 1, "name": "Informatika"}],
        "courses": [
            {"id": 1, "name": "Analiza 1", "semester": 1, "depId": 1,
             "quota": {"theory": 2, "practice": 2}},
        ],
        "studentsEnrolled": [{"depId": 1, "semester": 1, "count": 30}],
    }

    parsed = TypeAdapter(SchedulingInput).validate_python(legacy)

    assert [t.name for t in parsed.tracks] == ["Informatika"]
    assert parsed.courses[0].track_id == 1
    assert parsed.students_enrolled[0].track_id == 1


def test_print_group():
    from src.algo.data import print_group, Group
    from src.algo.model import StudyTrack

    # Arrange
    tracks = [
        StudyTrack(id=1, name="Profesor Matematike i Računarstva"),
    ]
    group = Group(id="1_1_1", track_id=1, count=30, semester=1)

    assert (
        print_group(group, tracks) == "Profesor Matematike i Računarstva, grupa B"
    )


def test_courses_for_track():
    from src.algo.model import Course, Quota

    quota = Quota(2, 3)
    # Arrange
    courses = [
        Course(
            id=1,
            name="Course 1",
            semester=1,
            track_id=10,
            quota=quota,
            needsComputers=False,
        ),
        Course(
            id=2,
            name="Course 2",
            semester=1,
            track_id=20,
            quota=quota,
            needsComputers=False,
        ),
        Course(
            id=3,
            name="Course 3",
            semester=1,
            track_id=10,
            quota=quota,
            needsComputers=False,
        ),
    ]
    # The function should filter only courses with trackId = 10
    from src.algo.data import courses_for_track

    result = list(courses_for_track(courses, 10))

    # Assert
    assert len(result) == 2
    assert all(course.track_id == 10 for course in result)
    ids = [course.id for course in result]
    assert set(ids) == {1, 3}


def test_generate_session_id():
    from src.algo.data import generate_session_id

    group_id = 5
    track_id = 2
    course_id = 17
    course_type = "p"

    session_id = generate_session_id(group_id, track_id, course_id, course_type, 0)
    assert session_id == "5_2_17_p_0"

    session_id = generate_session_id(group_id, track_id, course_id, course_type, 2)
    assert session_id == "5_2_17_p_2"


def test_track_by_id():
    from src.algo.model import StudyTrack
    from src.algo.data import track_by_id

    # Arrange
    tracks = [
        StudyTrack(id=1, name="Teorijska Matematika"),
        StudyTrack(id=2, name="Profesor Matematike"),
        StudyTrack(id=3, name="Informatika"),
    ]

    # Act
    result = track_by_id(tracks, 2)

    # Assert
    assert result is not None
    assert result.id == 2
    assert result.name == "Profesor Matematike"

    # Test for missing id
    missing = track_by_id(tracks, 99)
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
        group_ids=[],
        track_id="",
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
        group_ids=[],
        track_id="",
        course_id="",
        needs_computers=False,
        session_type="",
    )

    # Act
    eligible_room_ids = get_eligible_rooms(session, classrooms)

    # Assert
    assert eligible_room_ids == [1, 2, 3, 4]


def test_get_eligible_rooms_respects_capacity_when_enabled():
    # Arrange
    classrooms = [
        Classroom(**{"id": 1, "name": "Mala", "has_computers": False, "locId": 1,
                     "capacity": 20}),
        Classroom(**{"id": 2, "name": "Velika", "has_computers": False, "locId": 1,
                     "capacity": 100}),
    ]
    session = Session(
        id="",
        group_ids=["g1", "g2"],
        track_id="",
        course_id="",
        needs_computers=False,
        session_type="",
        size=60,
    )

    # bez check_capacity kapacitet se ignorise
    assert get_eligible_rooms(session, classrooms) == [1, 2]
    # sa check_capacity samo dovoljno velike ucionice
    assert get_eligible_rooms(session, classrooms, check_capacity=True) == [2]


def test_build_groups_prefers_explicit_groups():
    from src.algo.data import build_groups
    from src.algo.model import SchedulingInput, GroupDef, StudentsEnrolled

    scheduling_input = SchedulingInput(
        settings=mock_settings,
        locations=[],
        classrooms=[],
        tracks=[],
        courses=[],
        students_enrolled=[StudentsEnrolled(track_id=1, semester=1, count=90)],
        groups=[
            GroupDef(id="1i1", track_id=1, semester=1, count=35),
            GroupDef(id="1i2", track_id=1, semester=1, count=35),
        ],
    )

    groups = build_groups(scheduling_input, group_size=50)
    assert [g.id for g in groups] == ["1i1", "1i2"]
    assert all(g.count == 35 for g in groups)


def test_build_groups_falls_back_to_students_enrolled():
    from src.algo.data import build_groups
    from src.algo.model import SchedulingInput, StudentsEnrolled

    scheduling_input = SchedulingInput(
        settings=mock_settings,
        locations=[],
        classrooms=[],
        tracks=[],
        courses=[],
        students_enrolled=[StudentsEnrolled(track_id=1, semester=1, count=90)],
    )

    groups = build_groups(scheduling_input, group_size=50)
    assert [g.id for g in groups] == ["1_1_0", "1_1_1"]


def test_build_groups_from_staff_group_ids():
    from src.algo.data import build_groups
    from src.algo.model import (
        SchedulingInput, StudentsEnrolled, Course, Quota,
        StaffInput, TeachingAssignment,
    )

    scheduling_input = SchedulingInput(
        settings=mock_settings,
        locations=[],
        classrooms=[],
        tracks=[],
        courses=[
            Course(id=1, name="Kurs", semester=1, track_id=1,
                   quota=Quota(theory=1, practice=0), needsComputers=False),
        ],
        students_enrolled=[StudentsEnrolled(track_id=1, semester=1, count=100)],
    )
    staff_input = StaffInput(
        assignments=[
            TeachingAssignment(
                teacher_id=1, course_id=1, session_type="theory",
                group_ids=["1i1", "1i2"],
            ),
        ],
    )

    groups = build_groups(scheduling_input, group_size=50, staff_input=staff_input)
    assert [g.id for g in groups] == ["1i1", "1i2"]
    assert [g.count for g in groups] == [50, 50]


def test_build_groups_staff_generic_track_stays_synthetic():
    from src.algo.data import build_groups
    from src.algo.model import (
        SchedulingInput, StudentsEnrolled, Course, Quota,
        StaffInput, TeachingAssignment,
    )

    scheduling_input = SchedulingInput(
        settings=mock_settings,
        locations=[],
        classrooms=[],
        tracks=[],
        courses=[
            Course(id=1, name="I", semester=1, track_id=6,
                   quota=Quota(theory=1, practice=0), needsComputers=False),
            Course(id=2, name="S", semester=1, track_id=5,
                   quota=Quota(theory=1, practice=0), needsComputers=False),
        ],
        students_enrolled=[
            StudentsEnrolled(track_id=6, semester=1, count=100),
            StudentsEnrolled(track_id=5, semester=1, count=26),
        ],
    )
    staff_input = StaffInput(
        assignments=[
            TeachingAssignment(
                teacher_id=1, course_id=1, session_type="theory",
                group_ids=["1i1", "1i2"],
            ),
            TeachingAssignment(
                teacher_id=2, course_id=2, session_type="theory",
            ),
        ],
    )

    groups = build_groups(scheduling_input, group_size=50, staff_input=staff_input)
    by_id = {g.id: g for g in groups}
    assert by_id["1i1"].count == 50
    assert by_id["1i2"].count == 50
    assert "5_1_0" in by_id
    assert by_id["5_1_0"].count == 26


def test_build_cohorts_joint_and_individual():
    from src.algo.data import Group, build_cohorts
    from src.algo.model import Course, Quota, TeachingAssignment

    course = Course(
        id=10, name="Test", semester=1, track_id=1,
        quota=Quota(theory=2, practice=2), needsComputers=False,
    )
    groups = [Group("ga", 1, 30, 1), Group("gb", 1, 30, 1), Group("gc", 1, 30, 1)]
    assignments = [
        # ga i gb slusaju teoriju zajedno kod nastavnika 7
        TeachingAssignment(teacher_id=7, course_id=10, session_type="theory",
                           group_ids=["ga", "gb"]),
        # genericka dodela vezbi: svaka grupa pojedinacno kod nastavnika 9
        TeachingAssignment(teacher_id=9, course_id=10, session_type="practice"),
    ]

    theory = build_cohorts(course, "theory", groups, assignments)
    assert [c.group_ids for c in theory] == [["ga", "gb"], ["gc"]]
    assert [c.teacher_id for c in theory] == [7, None]
    assert theory[0].size == 60

    practice = build_cohorts(course, "practice", groups, assignments)
    assert [c.group_ids for c in practice] == [["ga"], ["gb"], ["gc"]]
    assert all(c.teacher_id == 9 for c in practice)


def test_build_cohorts_unknown_group_raises():
    from src.algo.data import Group, build_cohorts
    from src.algo.model import Course, Quota, TeachingAssignment

    course = Course(
        id=10, name="Test", semester=1, track_id=1,
        quota=Quota(theory=1, practice=0), needsComputers=False,
    )
    groups = [Group("ga", 1, 30, 1)]
    assignments = [
        TeachingAssignment(teacher_id=7, course_id=10, session_type="theory",
                           group_ids=["nonexistent"]),
    ]

    with pytest.raises(ValueError):
        build_cohorts(course, "theory", groups, assignments)


def test_generate_sessions():
    from src.algo.model import (
        SchedulingInput,
        StudentsEnrolled,
        Quota,
        Course,
        Quota,
        StudyTrack,
    )

    from src.algo.data import (
        generate_sessions,
    )

    # Arrange
    tracks = [
        StudyTrack(id=10, name="Informatika"),
        StudyTrack(id=20, name="Teorijska Matematika"),
    ]
    students_enrolled = [
        StudentsEnrolled(track_id=10, count=90, semester=1),
        StudentsEnrolled(track_id=20, count=100, semester=1),
    ]
    courses = [
        Course(
            id=101,
            name="Uvod u Programiranje",
            semester=1,
            track_id=10,
            quota=Quota(theory=1, practice=2),
            need_computers=True,
        ),
        Course(
            id=103,
            name="Analiza 1",
            semester=1,
            track_id=20,
            quota=Quota(theory=2, practice=3),
            need_computers=False,
        ),
    ]
    scheduling_input = SchedulingInput(
        students_enrolled=students_enrolled,
        courses=courses,
        tracks=tracks,
        locations=[],
        classrooms=[],
        settings=mock_settings,
    )

    # Act
    # redosled: kurs po kurs, prvo teorija pa vezbe, kohorta po kohorta
    result = list(generate_sessions(scheduling_input, group_size=50))
    assert result[0].id == "10_1_0_10_101_t_0"
    assert result[1].id == "10_1_1_10_101_t_0"
    assert result[2].id == "10_1_0_10_101_p_0"
    assert result[3].id == "10_1_0_10_101_p_1"
    assert result[4].id == "10_1_1_10_101_p_0"
    assert result[5].id == "10_1_1_10_101_p_1"

    assert result[6].id == "20_1_0_20_103_t_0"
    assert result[7].id == "20_1_0_20_103_t_1"
    assert result[8].id == "20_1_1_20_103_t_0"
    assert result[9].id == "20_1_1_20_103_t_1"
    assert result[10].id == "20_1_0_20_103_p_0"
    assert result[11].id == "20_1_0_20_103_p_1"
    assert result[12].id == "20_1_0_20_103_p_2"
    assert result[13].id == "20_1_1_20_103_p_0"
    assert result[14].id == "20_1_1_20_103_p_1"
    assert result[15].id == "20_1_1_20_103_p_2"

    # svaka sesija ima jednu grupu (nema staff inputa, nema zajednickih)
    assert all(len(s.group_ids) == 1 for s in result)
    # size = broj studenata u grupi (90 // 2 = 45)
    assert result[0].size == 45


def test_generate_sessions_with_joint_assignment():
    from src.algo.model import (
        SchedulingInput, StudentsEnrolled, Course, Quota, StaffInput,
        TeachingAssignment,
    )
    from src.algo.data import generate_sessions

    scheduling_input = SchedulingInput(
        settings=mock_settings,
        locations=[],
        classrooms=[],
        tracks=[],
        courses=[
            Course(id=1, name="Kurs", semester=1, track_id=1,
                   quota=Quota(theory=2, practice=1), needsComputers=False),
        ],
        students_enrolled=[StudentsEnrolled(track_id=1, semester=1, count=55)],
    )
    staff_input = StaffInput(
        teachers=[],
        assignments=[
            TeachingAssignment(teacher_id=7, course_id=1, session_type="theory",
                               group_ids=["ga", "gb"]),
        ],
    )

    result = list(generate_sessions(scheduling_input, 50, staff_input))

    theory = [s for s in result if s.session_type == "theory"]
    practice = [s for s in result if s.session_type == "practice"]

    # teorija: jedna zajednicka sesija po casu (2 casa), a ne po grupi
    assert len(theory) == 2
    assert all(s.group_ids == ["ga", "gb"] for s in theory)
    assert all(s.teacher_id == 7 for s in theory)
    assert all(s.size == 55 for s in theory)

    # vezbe: bez dodele -> svaka grupa svoju sesiju, bez nastavnika
    assert len(practice) == 2
    assert sorted(s.group_ids[0] for s in practice) == ["ga", "gb"]
    assert all(s.teacher_id is None for s in practice)


def _computer_need_input(needs_computers):
    from src.algo.model import SchedulingInput, GroupDef, Course, Quota

    return SchedulingInput(
        settings=mock_settings,
        locations=[],
        classrooms=[],
        tracks=[],
        courses=[
            Course(id=1, name="Programiranje 1", semester=1, track_id=1,
                   quota=Quota(theory=2, practice=1),
                   needsComputers=needs_computers),
        ],
        students_enrolled=[],
        groups=[GroupDef(id="ga", track_id=1, semester=1, count=30)],
    )


def test_generate_sessions_computers_only_for_practice():
    from src.algo.data import generate_sessions

    scheduling_input = _computer_need_input({"theory": False, "practice": True})

    result = list(generate_sessions(scheduling_input, 50))
    theory = [s for s in result if s.session_type == "theory"]
    practice = [s for s in result if s.session_type == "practice"]

    assert len(theory) == 2 and len(practice) == 1
    assert all(not s.needs_computers for s in theory)
    assert all(s.needs_computers for s in practice)


def test_generate_sessions_computers_only_for_theory():
    from src.algo.data import generate_sessions

    scheduling_input = _computer_need_input({"theory": True, "practice": False})

    result = list(generate_sessions(scheduling_input, 50))

    assert all(
        s.needs_computers == (s.session_type == "theory") for s in result
    )


def test_scalar_needs_computers_applies_to_both_session_types():
    """Stari (skalarni) oblik ulaza mora dati nepromenjeno ponasanje."""
    from src.algo.data import generate_sessions

    result = list(generate_sessions(_computer_need_input(True), 50))
    assert all(s.needs_computers for s in result)

    result = list(generate_sessions(_computer_need_input(0), 50))
    assert all(not s.needs_computers for s in result)


def test_needs_computers_for_rejects_unknown_session_type():
    from src.algo.model import Course, Quota

    course = Course(id=1, name="Kurs", semester=1, track_id=1,
                    quota=Quota(theory=1, practice=1), needsComputers=True)

    with pytest.raises(ValueError):
        course.needs_computers_for("lab")


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
