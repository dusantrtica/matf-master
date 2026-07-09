import string
from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass
from typing import List, Optional

_config = ConfigDict(populate_by_name=True)


@dataclass(config=_config)
class Location:
    id: int
    name: str


@dataclass(config=_config)
class Classroom:
    id: int
    name: str
    loc_id: int = Field(alias="locId")
    has_computers: bool = Field(alias="hasComputers")
    capacity: int = 0


@dataclass(config=_config)
class Department:
    id: int
    name: str


@dataclass(config=_config)
class Quota:
    def __init__(self, theory: int, practice:int):
        self.theory = theory
        self.practice = practice
    theory: int
    practice: int


@dataclass(config=_config)
class Course:
    id: int
    name: str
    semester: int
    dep_id: int = Field(alias="depId")
    quota: Quota = Field(default_factory=Quota)
    needs_computers: bool = Field(default=False, alias="needsComputers")


@dataclass(config=_config)
class StudentsEnrolled:
    dep_id: int = Field(alias="depId")
    semester: int = 0
    count: int = 0


@dataclass(config=_config)
class Settings:
    working_days: List[str] = Field(alias="workingDays")
    start_hour: int = Field(alias="startHour")
    end_hour: int = Field(alias="endHour")
    duration: int = 1


@dataclass(config=_config)
class RuleConfig:
    enabled: bool = True
    penalty: int = 0
    params: dict = Field(default_factory=dict)


@dataclass(config=_config)
class SchedulingInput:
    settings: Settings
    locations: List[Location]
    classrooms: List[Classroom]
    departments: List[Department]
    courses: List[Course]
    students_enrolled: List[StudentsEnrolled] = Field(alias="studentsEnrolled")
    rules: dict[str, RuleConfig] = Field(default_factory=dict)


@dataclass(config=_config)
class Teacher:
    id: int
    name: str
    # Opciono nadjacava podrazumevani broj radnih dana iz pravila
    # staffMaxWorkingDays (npr. -predrag.janicic_3day iz ulaznog fajla).
    max_working_days: Optional[int] = Field(default=None, alias="maxWorkingDays")


@dataclass(config=_config)
class TeachingAssignment:
    """Ko drzi koji kurs: (courseId, sessionType) -> nastavnik.

    sessionType je "theory" ili "practice". Ako je group_index zadat,
    dodela vazi samo za tu grupu (vezbe cesto drze razliciti asistenti
    po grupama); inace vazi za sve grupe kursa.
    """
    teacher_id: int = Field(alias="teacherId")
    course_id: int = Field(alias="courseId")
    session_type: str = Field(alias="sessionType")
    group_index: Optional[int] = Field(default=None, alias="groupIndex")


@dataclass(config=_config)
class StaffInput:
    teachers: List[Teacher] = Field(default_factory=list)
    assignments: List[TeachingAssignment] = Field(default_factory=list)
    rules: dict[str, RuleConfig] = Field(default_factory=dict)


