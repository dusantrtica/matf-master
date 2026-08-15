import math
import json
from functional import seq
from pathlib import Path
from pydantic import TypeAdapter
from typing import Iterable, List
from src.algo.model import (
    SchedulingInput,
    Course,
    StudyTrack,
    StudentsEnrolled,
    Classroom,
    StaffInput,
    TeachingAssignment,
)

GROUP_SIZE = 50  # 50 ucenika po grupi


def courses_for_track(courses: List[Course], track_id) -> List[Course]:
    return seq(courses).filter(lambda course: course.track_id == track_id).to_list()


def courses_for_group(courses: List[Course], track_id, semester) -> List[Course]:
    """Filter courses matching a group's track and semester.

    A group represents a (track, semester) cohort, so it only attends
    courses whose `track_id` AND `semester` match. Without the semester filter,
    a year-1 group would also be assigned year-2/3/4 courses.
    """
    return (
        seq(courses)
        .filter(lambda c: c.track_id == track_id and c.semester == semester)
        .to_list()
    )


class Group:
    def __init__(self, id: str, track_id: int, count: int, semester: int):
        self.id = id
        self.track_id = track_id
        self.count = count
        self.semester = semester

    def __eq__(self, value: object, /) -> bool:
        return self.id == value.id and self.count == value.count

    def __repr__(self) -> str:
        return f"{self.id}_{self.count}"

    def group_label(self):
        # sinteticke grupe imaju id oblika '{track}_{sem}_{index}' -> slovo;
        # eksplicitne grupe (npr. '1i1') koriste svoj id kao labelu
        parts = self.id.split("_")
        if len(parts) > 1 and parts[-1].isdigit():
            return "ABCDE"[int(parts[-1])]
        return self.id

def print_group(group: Group, tracks: List[StudyTrack]) -> str:
    track_name = track_by_id(tracks, group.track_id).name
    return f"{track_name}, grupa {group.group_label()}"


def split_students_into_groups(
    students_enrollment: List[StudentsEnrolled], group_size
) -> List[Group]:
    groups: List[Group] = []
    for enrollment in students_enrollment:
        number_of_groups = math.ceil(enrollment.count / group_size)
        for group_index in range(number_of_groups):
            group_id = f"{enrollment.track_id}_{enrollment.semester}_{group_index}"
            group = Group(
                group_id,
                enrollment.track_id,
                enrollment.count // number_of_groups,
                enrollment.semester,
            )
            groups.append(group)

    return groups


def build_groups(scheduling_input: SchedulingInput, group_size: int) -> List[Group]:
    """Grupe iz eksplicitne `groups` sekcije ako postoji, inace se
    izvode iz studentsEnrolled deljenjem na grupe velicine group_size."""
    if scheduling_input.groups:
        return [
            Group(g.id, g.track_id, g.count, g.semester)
            for g in scheduling_input.groups
        ]
    return split_students_into_groups(scheduling_input.students_enrolled, group_size)


def generate_session_id(
    group_id: int, track_id: int, course_id, course_type, index: int
) -> str:
    return f"{group_id}_{track_id}_{course_id}_{course_type}_{index}"


class Session:
    def __init__(
        self, id, group_ids, track_id, course_id, needs_computers,
        session_type: str, teacher_id: int | None = None, size: int = 0,
    ):
        self.id = id
        # sve grupe koje prisustvuju sesiji; vise grupa = zajednicko
        # predavanje (npr. oba toka slusaju isti cas)
        self.group_ids: list[str] = list(group_ids)
        self.course_id = course_id
        self.track_id = track_id
        self.needs_computers = needs_computers
        self.session_type = session_type
        # None znaci da nema dodeljenog nastavnika pa se staff pravila
        # ne primenjuju na ovu sesiju
        self.teacher_id = teacher_id
        # ukupan broj studenata (zbir po grupama), za kapacitet ucionice
        self.size = size


def format_teacher_name(name: str) -> str:
    """'predrag.janicic' -> 'Predrag Janicic'."""
    return " ".join(part.capitalize() for part in name.split("."))


def print_session(session: Session, groups: List[Group], courses: List[Course],
                   tracks: List[StudyTrack], room_name: str = "",
                   teacher_name: str = "") -> str:
    course_name = seq(courses).find(lambda c: c.id == session.course_id).name
    session_type = "T" if session.session_type == "theory" else "P"

    label = f"{course_name} ({session_type})"
    if teacher_name:
        label += f"\n{format_teacher_name(teacher_name)}"
    if room_name:
        label += f"\n{room_name}"
    return label


def track_by_id(tracks: List[StudyTrack], id: int) -> StudyTrack:
    return seq(tracks).find(lambda track: track.id == id)


class Cohort:
    """Skup grupa koje zajedno slusaju sesije jednog kursa/tipa,
    sa (opcionim) nastavnikom koji ih drzi."""

    def __init__(self, groups: List[Group], teacher_id: int | None):
        self.groups = groups
        self.teacher_id = teacher_id

    @property
    def group_ids(self) -> list[str]:
        return [g.id for g in self.groups]

    @property
    def size(self) -> int:
        return sum(g.count for g in self.groups)

    @property
    def label(self) -> str:
        return "+".join(self.group_ids)


def build_cohorts(
    course: Course,
    session_type: str,
    course_groups: List[Group],
    assignments: List[TeachingAssignment],
) -> List[Cohort]:
    """Deli grupe kursa u kohorte za dati tip sesije.

    - Dodela sa group_ids pravi jednu zajednicku kohortu tih grupa.
    - Dodela bez group_ids (genericka) vazi za svaku preostalu grupu
      pojedinacno.
    - Grupe bez ikakve dodele postaju pojedinacne kohorte bez nastavnika.
    """
    groups_by_id = {g.id: g for g in course_groups}
    remaining = dict(groups_by_id)  # cuva redosled ubacivanja

    cohorts: List[Cohort] = []
    generic_teacher: int | None = None

    for a in assignments:
        if a.course_id != course.id or a.session_type != session_type:
            continue
        if a.group_ids is None:
            generic_teacher = a.teacher_id
            continue

        unknown = [g for g in a.group_ids if g not in groups_by_id]
        if unknown:
            raise ValueError(
                f"Assignment for course {course.id} ({session_type}) references "
                f"unknown group(s) {unknown}; valid groups: {sorted(groups_by_id)}"
            )
        cohorts.append(
            Cohort([groups_by_id[g] for g in a.group_ids], a.teacher_id)
        )
        for g in a.group_ids:
            remaining.pop(g, None)

    for g in remaining.values():
        cohorts.append(Cohort([g], generic_teacher))

    return cohorts


def generate_sessions(
    scheduling_input: SchedulingInput,
    group_size: int,
    staff_input: StaffInput | None = None,
) -> Iterable[Session]:
    groups: List[Group] = build_groups(scheduling_input, group_size)
    assignments = staff_input.assignments if staff_input else []

    sessions: List[Session] = []
    for course in scheduling_input.courses:
        course_groups = [
            g for g in groups
            if g.track_id == course.track_id and g.semester == course.semester
        ]
        if not course_groups:
            continue

        for session_type, type_code, quota in (
            ("theory", "t", course.quota.theory),
            ("practice", "p", course.quota.practice),
        ):
            for cohort in build_cohorts(course, session_type, course_groups, assignments):
                for i in range(quota):
                    sessions.append(
                        Session(
                            generate_session_id(
                                cohort.label, course.track_id, course.id, type_code, i
                            ),
                            cohort.group_ids,
                            course.track_id,
                            course.id,
                            course.needs_computers,
                            session_type,
                            teacher_id=cohort.teacher_id,
                            size=cohort.size,
                        )
                    )

    return sessions


def get_eligible_rooms(
    session: Session, classrooms: list[Classroom], check_capacity: bool = False
) -> list[int]:
    eligible: list[int] = []
    for room in classrooms:    
        if session.needs_computers and not room.has_computers:
            continue
        if check_capacity and session.size > 0 and room.capacity < session.size:
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
