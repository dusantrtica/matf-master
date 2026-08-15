import string
from pydantic import AliasChoices, ConfigDict, Field
from pydantic.dataclasses import dataclass
from typing import List, Optional

_config = ConfigDict(populate_by_name=True)

# Raniji nazivi (`depId`, `departments`) i dalje se prihvataju kako bi
# postojeci ulazni fajlovi radili bez izmena.
_TRACK_ID_ALIASES = AliasChoices("trackId", "depId")


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
class StudyTrack:
    """Smer studija (npr. Informatika, Teorijska matematika)."""
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
    track_id: int = Field(
        validation_alias=_TRACK_ID_ALIASES, serialization_alias="trackId"
    )
    quota: Quota = Field(default_factory=Quota)
    needs_computers: bool = Field(default=False, alias="needsComputers")


@dataclass(config=_config)
class StudentsEnrolled:
    track_id: int = Field(
        validation_alias=_TRACK_ID_ALIASES, serialization_alias="trackId"
    )
    semester: int = 0
    count: int = 0


@dataclass(config=_config)
class GroupDef:
    """Eksplicitno definisana grupa (kohorta) studenata.

    Ako je sekcija `groups` prisutna u ulazu, grupe se ne izvode iz
    studentsEnrolled + GROUP_SIZE nego se koriste ovako zadate.
    """
    id: str
    track_id: int = Field(
        validation_alias=_TRACK_ID_ALIASES, serialization_alias="trackId"
    )
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
    courses: List[Course]
    tracks: List[StudyTrack] = Field(
        validation_alias=AliasChoices("tracks", "departments"),
        serialization_alias="tracks",
    )
    students_enrolled: List[StudentsEnrolled] = Field(alias="studentsEnrolled")
    rules: dict[str, RuleConfig] = Field(default_factory=dict)
    groups: List[GroupDef] = Field(default_factory=list)


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

    sessionType je "theory" ili "practice".

    - group_ids sa vise grupa: te grupe slusaju ZAJEDNO, pravi se jedna
      zajednicka sesija (npr. zajednicko predavanje za oba toka).
    - group_ids sa jednom grupom: dodela vazi samo za tu grupu.
    - group_ids None: dodela vazi za svaku (preostalu) grupu kursa
      pojedinacno - svaka grupa ima svoju sesiju sa ovim nastavnikom.
    """
    teacher_id: int = Field(alias="teacherId")
    course_id: int = Field(alias="courseId")
    session_type: str = Field(alias="sessionType")
    group_ids: Optional[List[str]] = Field(default=None, alias="groupIds")


@dataclass(config=_config)
class StaffInput:
    teachers: List[Teacher] = Field(default_factory=list)
    assignments: List[TeachingAssignment] = Field(default_factory=list)
    rules: dict[str, RuleConfig] = Field(default_factory=dict)


