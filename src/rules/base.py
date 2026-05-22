from abc import ABC, abstractmethod
from ortools.sat.python import cp_model
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.algo.cp_solver import SimpleCPSolver


class SchedulingRule(ABC):
    """Base class for all scheduling rules (plugin interface).

    Each rule can be either a hard constraint (penalty=0) or a soft
    constraint (penalty>0).  When soft, the solver tries to satisfy it
    but can violate it at the given cost per violation.
    """

    def __init__(self, enabled: bool = True, penalty: int = 0, **kwargs):
        self.enabled = enabled
        self.penalty = penalty

    @property
    def is_hard(self) -> bool:
        return self.penalty == 0

    @abstractmethod
    def apply(self, solver: "SimpleCPSolver") -> list[cp_model.IntVar]:
        """Apply this rule to the CP model.

        Returns a list of BoolVar penalty indicators (1 = violation)
        for soft constraints.  Hard constraints return [].
        """
        ...
