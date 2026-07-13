"""Rule: bez procepa u rasporedu jedne grupe

Procep je slobodan sat koji se nalazi izmedju dva zauzeta sata u istom danu
za istu grupu. Npr. ako grupa ima cas u 8h i u 11h, a 9h i 10h su slobodni,
to su dva procepa.

Pravilo radi kao hard ogranicenje (penalty == 0, zabranjuje sve procepe)
ili kao soft ogranicenje (penalty > 0, minimizuje broj procepa).
"""

from collections import defaultdict
from ortools.sat.python import cp_model
from src.rules.base import SchedulingRule
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.algo.cp_solver import SimpleCPSolver


class NoGapsInScheduleRule(SchedulingRule):

    def apply(self, solver: "SimpleCPSolver") -> list[cp_model.IntVar]:
        D = len(solver.settings.working_days)
        H = len(solver.working_hours)

        # group_id -> globalni indeksi sesija te grupe
        # (zajednicka sesija se racuna svakoj grupi koja je pohadja)
        group_sessions: dict[int, list[int]] = defaultdict(list)
        for s, session in enumerate(solver.sessions):
            for group_id in session.group_ids:
                group_sessions[group_id].append(s)

        gap_vars: list[cp_model.IntVar] = []
        for g, sess in group_sessions.items():
            busy = self._build_busy(solver, g, sess, D, H)
            for d in range(D):
                gap_vars.extend(self._gaps_for_day(solver, g, d, busy[d], H))

        if self.is_hard:
            # hard - zabranjujemo svaki procep; ako se ne ispuni solver
            # prijavljuje INFEASIBLE
            for gap in gap_vars:
                solver.model.Add(gap == 0)
            return []

        # soft - vracamo procepe kao violation varijable koje solver minimizuje
        return gap_vars

    def _build_busy(
        self,
        solver: "SimpleCPSolver",
        g: int,
        sess: list[int],
        D: int,
        H: int,
    ) -> dict[int, list[cp_model.IntVar]]:
        """busy[d][h] == 1 ako grupa g ima cas u danu d, satu h.

        Koristimo flat_time_var[s] == d*H + h (jedinstven indeks vremena u
        nedelji) pa nam ne trebaju proizvodi day_var*slot_var. busy je OR
        reifikovanih jednakosti preko svih sesija grupe.
        """
        busy: dict[int, list[cp_model.IntVar]] = {}
        for d in range(D):
            row: list[cp_model.IntVar] = []
            for h in range(H):
                t = d * H + h
                lits: list[cp_model.IntVar] = []
                for s in sess:
                    lit = solver.model.NewBoolVar(f"at_{s}_{t}")
                    solver.model.Add(solver.flat_time_var[s] == t).OnlyEnforceIf(lit)
                    solver.model.Add(solver.flat_time_var[s] != t).OnlyEnforceIf(
                        lit.Not()
                    )
                    lits.append(lit)
                b = solver.model.NewBoolVar(f"busy_{g}_{d}_{h}")
                solver.model.AddMaxEquality(b, lits)  # OR preko sesija
                row.append(b)
            busy[d] = row
        return busy

    def _gaps_for_day(
        self,
        solver: "SimpleCPSolver",
        g: int,
        d: int,
        busy_day: list[cp_model.IntVar],
        H: int,
    ) -> list[cp_model.IntVar]:
        """Sat h je procep ako je slobodan, a postoji zauzet sat i pre i
        posle njega u istom danu. Rubni satovi (0 i H-1) ne mogu biti
        unutrasnji procep pa ih preskacemo.
        """
        gaps: list[cp_model.IntVar] = []
        for h in range(1, H - 1):
            has_before = solver.model.NewBoolVar(f"hb_{g}_{d}_{h}")
            solver.model.AddMaxEquality(has_before, busy_day[:h])
            has_after = solver.model.NewBoolVar(f"ha_{g}_{d}_{h}")
            solver.model.AddMaxEquality(has_after, busy_day[h + 1:])

            gap = solver.model.NewBoolVar(f"gap_{g}_{d}_{h}")
            # gap == has_before AND has_after AND NOT busy[h]
            solver.model.AddBoolAnd(
                [has_before, has_after, busy_day[h].Not()]
            ).OnlyEnforceIf(gap)
            solver.model.AddBoolOr(
                [has_before.Not(), has_after.Not(), busy_day[h]]
            ).OnlyEnforceIf(gap.Not())
            gaps.append(gap)
        return gaps
