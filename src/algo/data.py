import math
import json
from functional import seq
from pathlib import Path
from tokenize import group
from pydantic import TypeAdapter
from typing import Generator, Iterable, List
from src.algo.model import (
    SchedulingInput,
    Course,
    Department,
    StudentsEnrolled,
    Classroom,
    StaffInput,
    TeachingAssignment,
)

GROUP_SIZE = 50  # 50 ucenika po grupi


def courses_for_department(courses: List[Course], department_id) -> List[Course]:
    return seq(courses).filter(lambda course: course.dep_id == department_id).to_list()


def courses_for_group(courses: List[Course], department_id, semester) -> List[Course]:
    """Filter courses matching a group's department and semester.

    A group represents a (department, semester) cohort, so it only attends
    courses whose `dep_id` AND `semester` match. Without the semester filter,
    a year-1 group would also be assigned year-2/3/4 courses.
    """
    return (
        seq(courses)
        .filter(lambda c: c.dep_id == department_id and c.semester == semester)
        .to_list()
    )


class Group:
    def __init__(self, id: str, dep_id: Department, count: int, semester: int):
        self.id = id
        self.department_id = dep_id
        self.count = count
        self.semester = semester

    def __eq__(self, value: object, /) -> bool:
        return self.id == value.id and self.count == value.count

    def __repr__(self) -> str:
        return f"{self.id}_{self.count}"

    def group_label(self):
        grp_index = int(self.id.split("_")[-1])
        return "ABCDE"[grp_index]

def print_group(group: Group, departments: List[Department]) -> str:
    department_name = department_by_id(departments, group.department_id).name
    return f"{department_name}, grupa {group.group_label()}"


def split_students_into_groups(
    students_enrollment: List[StudentsEnrolled], group_size
) -> List[Group]:
    groups: List[Group] = []
    for enrollment in students_enrollment:
        number_of_groups = math.ceil(enrollment.count / group_size)
        for group_index in range(number_of_groups):
            group_id = f"{enrollment.dep_id}_{enrollment.semester}_{group_index}"
            group = Group(
                group_id,
                enrollment.dep_id,
                enrollment.count // number_of_groups,
                enrollment.semester,
            )
            groups.append(group)

    return groups


def generate_session_id(
    group_id: int, department_id: int, course_id, course_type, index: int
) -> str:
    return f"{group_id}_{department_id}_{course_id}_{course_type}_{index}"


class Session:
    def __init__(
        self, id, group_id, department_id, course_id, needs_computers, session_type: str,
        teacher_id: int | None = None,
    ):
        self.id = id
        self.group_id = group_id
        self.course_id = course_id
        self.department_id = department_id
        self.needs_computers = needs_computers
        self.session_type = session_type
        # None znaci da nema dodeljenog nastavnika pa se staff pravila
        # ne primenjuju na ovu sesiju
        self.teacher_id = teacher_id


def format_teacher_name(name: str) -> str:
    """'predrag.janicic' -> 'Predrag Janicic'."""
    return " ".join(part.capitalize() for part in name.split("."))


def print_session(session: Session, groups: List[Group], courses: List[Course],
                   departments: List[Department], room_name: str = "",
                   teacher_name: str = "") -> str:
    course_name = seq(courses).find(lambda c: c.id == session.course_id).name
    session_type = "T" if session.session_type == "theory" else "P"

    label = f"{course_name} ({session_type})"
    if teacher_name:
        label += f"\n{format_teacher_name(teacher_name)}"
    if room_name:
        label += f"\n{room_name}"
    return label


def department_by_id(departments: List[Department], id: int) -> Department:
    return seq(departments).find(lambda dep: dep.id == id)


def course_sessions(course: Course, group_id: int) -> Generator[Session, None, None]:    
    for i in range(course.quota.theory):
        yield Session(
            generate_session_id(group_id, course.dep_id, course.id, "t", i),
            group_id,
            course.dep_id,
            course.id,
            course.needs_computers,
            "theory",
        )

    for i in range(course.quota.practice):
        yield Session(
            generate_session_id(group_id, course.dep_id, course.id, "p", i),
            group_id,
            course.dep_id,
            course.id,
            course.needs_computers,
            "practice",
        )


def generate_sessions(scheduling_input: SchedulingInput, group_size: int) -> Iterable[Session]:
    groups: List[Group] = split_students_into_groups(scheduling_input.students_enrolled, group_size)
    sessions: List[Session] = []
    for group in groups:
        for course in courses_for_group(
            scheduling_input.courses, group.department_id, group.semester
        ):
            for session in course_sessions(course, group.id):
                sessions.append(session)

    return sessions

def get_eligible_rooms(session: Session, classrooms: list[Classroom]) -> list[int]:
    eligible: list[int] = []
    for room in classrooms:    
        if session.needs_computers and not room.has_computers:
            continue
        eligible.append(room.id)
    return eligible

def load_input(path: str) -> SchedulingInput:
    raw = Path(path).read_text(encoding="utf-8")
    adapter = TypeAdapter(SchedulingInput)
    return adapter.validate_python(json.loads(raw))


def load_staff_input(path: str) -> StaffInput:
    raw = Path(path).read_text(encoding="utf-8")
    adapter = TypeAdapter(StaffInput)
    return adapter.validate_python(json.loads(raw))


def group_index_from_group_id(group_id: str) -> int:
    """Grupe se generisu sa id-jem oblika '{dep_id}_{semester}_{index}'."""
    return int(str(group_id).split("_")[-1])


def _find_assignment(
    session: Session, assignments: List[TeachingAssignment]
) -> TeachingAssignment | None:
    """Nadji dodelu nastavnika za sesiju.

    Dodela za konkretnu grupu (group_index) ima prednost nad opstom
    dodelom (group_index == None) za isti (course_id, session_type).
    """
    session_group_index = group_index_from_group_id(session.group_id)
    generic = None
    for a in assignments:
        if a.course_id != session.course_id or a.session_type != session.session_type:
            continue
        if a.group_index is None:
            generic = a
        elif a.group_index == session_group_index:
            return a
    return generic


def assign_teachers_to_sessions(
    sessions: Iterable[Session], staff_input: StaffInput
) -> None:
    """Upisuje teacher_id u sesije na osnovu dodela iz staff fajla.

    Sesije bez odgovarajuce dodele ostaju bez nastavnika (teacher_id=None)
    i na njih se staff pravila ne primenjuju.
    """
    for session in sessions:
        assignment = _find_assignment(session, staff_input.assignments)
        if assignment is not None:
            session.teacher_id = assignment.teacher_id
