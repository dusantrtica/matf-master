"""Rule: grupisati sesije iste grupe u bloku

Quota mapping (quotas are 1–4):
  1  → [1]     single session
  2  → [2]     dvosatni blok
  3  → [3]     trosatni blok
  4  → [2, 2]  dva dvosatna bloka
"""

from collections import defaultdict
from ortools.sat.python import cp_model
from src.rules.base import SchedulingRule
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.algo.cp_solver import SimpleCPSolver


def split_into_blocks(quota: int) -> list[int]:
    # ako je quota <= 3, pravimo jedan blok
    # npr trocas vezbi ili dvocas predavanja
    if quota <= 3:
        return [quota]

    # za predavanja npr Analiza1 koja ima 4 predavanja nedeljno
    # pravimo dva dvosatna bloka
    return [2, 2]


class JoinSameClassesRule(SchedulingRule):

    def apply(self, solver: "SimpleCPSolver") -> list[cp_model.IntVar]:
        # pravimo familije - sesije sa istim kursom, grupama i tipom sesije
        # to su sesije koje grupisemo u blokove (dvo, trosatni blokovi)
        # i svaki od tih blokova mora da bude u istom danu, ucionici i sat za satom.
        families: dict[tuple, list[int]] = defaultdict(list)
        for s, session in enumerate(solver.sessions):
            key = (session.course_id, tuple(session.group_ids), session.session_type)
            families[key].append(s)

        H = len(solver.working_hours)
        violations: list[cp_model.IntVar] = []

        for _family_key, family_sessions in families.items():
            # pravimo blokove - dvo, trosatni blokovi
            # blokovi su oblika: [1], [2], [3], [2, 2]
            block_sizes = split_into_blocks(len(family_sessions))

            offset = 0
            for block_size in block_sizes:
                if block_size <= 1:
                    offset += block_size
                    continue

                block = family_sessions[offset : offset + block_size]
                # anchor je prva sesija u bloku
                # koristimo je kao referentnu sesiju za ostale sesije u bloku
                # da bi ostale sesije bile u istom danu, ucionici i satu za satom.
                anchor = block[0]

                if self.is_hard:
                    # hard constraint - svaka sesija u bloku mora da bude u istom danu, ucionici i satu za satom.
                    # ako se ovo ne isputni, solver prijavljuje UNFEASIBLE
                    self._add_hard(solver, block, anchor, H)
                else:
                    # soft constraint - svaka sesija u bloku mora da bude u istom danu, ucionici i satu za satom.
                    # ako se ovo ne isputni, solver prijavljuje violation, ali moze da se resi.
                    # dodaje penalty varijablu za svaku sesiju u bloku.
                    violations.extend(self._add_soft(solver, block, anchor, H))

                offset += block_size

        return violations

    def _add_hard(
        self,
        solver: "SimpleCPSolver",
        block: list[int],
        anchor: int,
        H: int,
    ):
        for i, s in enumerate(block[1:], start=1):
            # za svaku sesiju u bloku, postavljamo da bude u istom danu kao i anchor - polazni blok
            solver.model.Add(solver.day_var[s] == solver.day_var[anchor])
            # postavljamo da bude u istom satu kao i anchor + i - 1
            solver.model.Add(solver.slot_var[s] == solver.slot_var[anchor] + i)
            # postavljamo da bude u istoj ucionici kao i anchor
            solver.model.Add(solver.room_var[s] == solver.room_var[anchor])

        # uslov da blok ne bude prevelik, da ne bude van radnog vremena,
        # tj da se zadnja sesija u bloku zavrsi pre kraja radnog vremena.
        solver.model.Add(solver.slot_var[anchor] + len(block) - 1 <= H - 1)

    def _add_soft(
        self,
        solver: "SimpleCPSolver",
        block: list[int],
        anchor: int,
        H: int,
    ) -> list[cp_model.IntVar]:
        # soft constraint - svaka sesija u bloku mora da bude u istom danu, ucionici i satu za satom.
        # ako se ovo ne ispuni, solver prijavljuje violation, ali moze da se resi.
        # dodaje penalty varijablu za svaku sesiju u bloku.
        b = solver.model.NewBoolVar(f"joined_{block[0]}_{block[-1]}")

        for i, s in enumerate(block[1:], start=1):
            solver.model.Add(
                solver.day_var[s] == solver.day_var[anchor]
            ).OnlyEnforceIf(b)
            solver.model.Add(
                solver.slot_var[s] == solver.slot_var[anchor] + i
            ).OnlyEnforceIf(b)
            solver.model.Add(
                solver.room_var[s] == solver.room_var[anchor]
            ).OnlyEnforceIf(b)

        solver.model.Add(
            solver.slot_var[anchor] + len(block) - 1 <= H - 1
        ).OnlyEnforceIf(b)

        violation = solver.model.NewBoolVar(f"violation_joined_{block[0]}_{block[-1]}")
        solver.model.Add(violation == 1).OnlyEnforceIf(b.Not())
        solver.model.Add(violation == 0).OnlyEnforceIf(b)

        return [violation]
