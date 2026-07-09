"""Rule: maksimalan broj sati pauze nastavnika u toku nedelje

Iz ulaznog fajla profesora: globalno ogranicenje kaze da nijedan nastavnik
ne sme imati vise od 1 sata pauze tokom cele nedelje (literali _hole1).
Pauza (procep) je slobodan sat izmedju dva zauzeta sata u istom danu.

Za razliku od NoGapsInScheduleRule (koje zabranjuje procepe grupa po danu),
ovde se procepi nastavnika sabiraju kroz celu nedelju i porede sa budzetom
maxGapHours (podrazumevano 1).

Hard (penalty == 0): sum(procepi u nedelji) <= max_gap_hours.
Soft (penalty > 0): minimizuje se broj procepa preko budzeta.
"""

from ortools.sat.python import cp_model
from src.rules.base import SchedulingRule
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.algo.cp_solver import SimpleCPSolver

DEFAULT_MAX_GAP_HOURS = 1


class StaffMaxGapHoursRule(SchedulingRule):

    def __init__(self, enabled: bool = True, penalty: int = 0, **kwargs):
        super().__init__(enabled=enabled, penalty=penalty, **kwargs)
        self.max_gap_hours = kwargs.get("maxGapHours", DEFAULT_MAX_GAP_HOURS)

    def apply(self, solver: "SimpleCPSolver") -> list[cp_model.IntVar]:
        D = len(solver.settings.working_days)
        H = len(solver.working_hours)

        violations: list[cp_model.IntVar] = []
        for teacher_id, session_indices in solver.teacher_sessions.items():
            # nastavnik sa jednom sesijom ne moze imati procep
            if len(session_indices) < 2:
                continue

            week_gaps: list[cp_model.IntVar] = []
            for d in range(D):
                busy_day = self._build_busy_day(
                    solver, teacher_id, session_indices, d, H
                )
                week_gaps.extend(
                    self._gaps_for_day(solver, teacher_id, d, busy_day, H)
                )

            total_gaps = sum(week_gaps)
            if self.is_hard:
                solver.model.Add(total_gaps <= self.max_gap_hours)
            else:
                # procepi preko budzeta, solver ih minimizuje
                excess = solver.model.NewIntVar(
                    0, D * H, f"staff_gap_excess_{teacher_id}"
                )
                solver.model.Add(excess >= total_gaps - self.max_gap_hours)
                violations.append(excess)

        return violations

    def _build_busy_day(
        self,
        solver: "SimpleCPSolver",
        teacher_id: int,
        session_indices: list[int],
        d: int,
        H: int,
    ) -> list[cp_model.IntVar]:
        """busy[h] == 1 ako nastavnik ima cas u danu d, satu h."""
        busy: list[cp_model.IntVar] = []
        for h in range(H):
            t = d * H + h
            lits: list[cp_model.IntVar] = []
            for s in session_indices:
                lit = solver.model.NewBoolVar(f"staff_at_{teacher_id}_{s}_{t}")
                solver.model.Add(solver.flat_time_var[s] == t).OnlyEnforceIf(lit)
                solver.model.Add(solver.flat_time_var[s] != t).OnlyEnforceIf(
                    lit.Not()
                )
                lits.append(lit)
            b = solver.model.NewBoolVar(f"staff_busy_{teacher_id}_{d}_{h}")
            solver.model.AddMaxEquality(b, lits)  # OR preko sesija
            busy.append(b)
        return busy

    def _gaps_for_day(
        self,
        solver: "SimpleCPSolver",
        teacher_id: int,
        d: int,
        busy_day: list[cp_model.IntVar],
        H: int,
    ) -> list[cp_model.IntVar]:
        """Sat h je procep ako je slobodan, a postoji zauzet sat i pre i
        posle njega u istom danu.
        """
        gaps: list[cp_model.IntVar] = []
        for h in range(1, H - 1):
            has_before = solver.model.NewBoolVar(f"staff_hb_{teacher_id}_{d}_{h}")
            solver.model.AddMaxEquality(has_before, busy_day[:h])
            has_after = solver.model.NewBoolVar(f"staff_ha_{teacher_id}_{d}_{h}")
            solver.model.AddMaxEquality(has_after, busy_day[h + 1:])

            gap = solver.model.NewBoolVar(f"staff_gap_{teacher_id}_{d}_{h}")
            # gap == has_before AND has_after AND NOT busy[h]
            solver.model.AddBoolAnd(
                [has_before, has_after, busy_day[h].Not()]
            ).OnlyEnforceIf(gap)
            solver.model.AddBoolOr(
                [has_before.Not(), has_after.Not(), busy_day[h]]
            ).OnlyEnforceIf(gap.Not())
            gaps.append(gap)
        return gaps
