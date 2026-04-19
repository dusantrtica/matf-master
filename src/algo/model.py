import string
from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass
from typing import List

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
class SchedulingInput:
    settings: Settings
    locations: List[Location]
    classrooms: List[Classroom]
    departments: List[Department]
    courses: List[Course]
    students_enrolled: List[StudentsEnrolled] = Field(alias="studentsEnrolled")


