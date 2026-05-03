"""
Benchmark harness for comparing CP-SAT vs MIP/SCIP solvers on class scheduling.

Runs both solvers on three real-world subsets of input_full_1_semester.json
(MATF-S, MATF-M, MATF-L) and prints a structured comparison report.

Usage:
    python -m src.algo.benchmark                       # all three scales
    python -m src.algo.benchmark --scales S M          # only S and M
    python -m src.algo.benchmark --json report.json    # save JSON report
    python -m src.algo.benchmark --max-time 120        # override time limits
"""

import argparse
import gc
import json
import math
import os
import resource
import time
import tracemalloc
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

from ortools.linear_solver import pywraplp
from ortools.sat.python import cp_model

from src.algo.cp_solver import SimpleCPSolver
from src.algo.data import GROUP_SIZE, Session, generate_sessions, load_input
from src.algo.mip_solver import SimpleMIPSolver
from src.algo.model import Classroom, SchedulingInput


# ---------------------------------------------------------------------------
# 1. BenchmarkResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkResult:
    solver_name: str
    scale_label: str
    num_sessions: int
    num_variables: int
    num_constraints: int
    construction_time_s: float
    solve_time_s: float
    total_time_s: float
    peak_memory_kb: float
    model_memory_kb: float
    status: str
    objective_value: Optional[float]
    optimality_gap: Optional[float]
    solution_valid: Optional[bool]


# ---------------------------------------------------------------------------
# 2. Solution validator
# ---------------------------------------------------------------------------

def validate_solution(
    sessions: List[Session],
    variables: List[dict],
    classrooms: List[Classroom],
) -> tuple:
    """
    Funkcija koja proverava da li je resenje validno
    u odnosu na hard constraints.
    Returns (is_valid, list_of_violations).
    """
    violations = []

    if len(variables) != len(sessions):
        violations.append(
            f"Broj sesija ne odgovara broju dodeljenih sesija: {len(sessions)} sesija vs "
            f"{len(variables)} dodeljenih sesija"
        )
        return False, violations

    room_time_set: set = set()
    group_time_map: Dict[str, set] = defaultdict(set)
    computer_room_indices = {
        i for i, room in enumerate(classrooms) if room.has_computers
    }

    for s, (session, v) in enumerate(zip(sessions, variables)):
        d, h, r = v["day"], v["hour"], v["room"]

        rt_key = (d, h, r)
        if rt_key in room_time_set:
            violations.append(
                f"Kolizija ucionice u danu={d} satu={h} ucionici={r} (sesija {s})"
            )
        room_time_set.add(rt_key)

        gt_key = (d, h)
        if gt_key in group_time_map[session.group_id]:
            violations.append(
                f"Kolizija sesije grupe={session.group_id} "
                f"dan={d} sat={h} (sesija {s})"
            )
        group_time_map[session.group_id].add(gt_key)

        if session.needs_computers and r not in computer_room_indices:
            violations.append(
                f"Ogranicenje racunara nije zadovoljeno: sesija {s} zahteva racunare "
                f"ali ucionica {r} nema racunara"
            )

    is_valid = len(violations) == 0
    return is_valid, violations


# ---------------------------------------------------------------------------
# 3. Benchmark runners for each solver type
# ---------------------------------------------------------------------------

CP_STATUS_NAMES = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}

MIP_STATUS_NAMES = {
    pywraplp.Solver.OPTIMAL: "OPTIMAL",
    pywraplp.Solver.FEASIBLE: "FEASIBLE",
    pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
    pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
    pywraplp.Solver.ABNORMAL: "ABNORMAL",
    pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
}


def _get_peak_rss_kb() -> float:
    """Maksimalna velicina RAM u KB (macOS ru_maxrss je u bajtovima)."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024


def benchmark_cp(
    scheduling_input: SchedulingInput,
    scale_label: str,
    max_time: float = 1e9,
) -> BenchmarkResult:
    gc.collect()
    tracemalloc.start()
    mem_before = tracemalloc.take_snapshot()

    t0 = time.perf_counter()
    solver = SimpleCPSolver(
        scheduling_input, max_time_seconds=max_time, log_progress=False
    )
    t_construct = time.perf_counter()

    mem_after_construct = tracemalloc.take_snapshot()

    num_vars = len(solver.model.Proto().variables)
    num_constraints = len(solver.model.Proto().constraints)

    status_code = solver.solve()
    t_solve = time.perf_counter()

    tracemalloc.stop()

    status = CP_STATUS_NAMES.get(status_code, str(status_code))

    objective_value = None
    gap = None
    solution_valid = None

    if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        objective_value = solver.solver.ObjectiveValue()
        best_bound = solver.solver.BestObjectiveBound()
        if objective_value != 0:
            gap = abs(objective_value - best_bound) / abs(objective_value)
        else:
            gap = 0.0

        variables = solver.get_solution_variables()
        valid, _ = validate_solution(
            solver.sessions, variables, scheduling_input.classrooms
        )
        solution_valid = valid

    model_stats = mem_after_construct.compare_to(mem_before, "lineno")
    model_mem_kb = sum(s.size_diff for s in model_stats) / 1024

    return BenchmarkResult(
        solver_name="CP-SAT",
        scale_label=scale_label,
        num_sessions=len(solver.sessions),
        num_variables=num_vars,
        num_constraints=num_constraints,
        construction_time_s=round(t_construct - t0, 4),
        solve_time_s=round(t_solve - t_construct, 4),
        total_time_s=round(t_solve - t0, 4),
        peak_memory_kb=round(_get_peak_rss_kb(), 1),
        model_memory_kb=round(model_mem_kb, 1),
        status=status,
        objective_value=objective_value,
        optimality_gap=round(gap, 6) if gap is not None else None,
        solution_valid=solution_valid,
    )


def benchmark_mip(
    scheduling_input: SchedulingInput,
    scale_label: str,
    max_time: float = 1e9,
) -> BenchmarkResult:
    gc.collect()
    tracemalloc.start()
    mem_before = tracemalloc.take_snapshot()

    t0 = time.perf_counter()
    solver = SimpleMIPSolver(scheduling_input, max_time_seconds=max_time)
    t_construct = time.perf_counter()

    mem_after_construct = tracemalloc.take_snapshot()

    num_vars = solver.solver.NumVariables()
    num_constraints = solver.solver.NumConstraints()

    status_code = solver.solve()
    t_solve = time.perf_counter()

    tracemalloc.stop()

    status = MIP_STATUS_NAMES.get(status_code, str(status_code))

    objective_value = None
    gap = None
    solution_valid = None

    if status_code in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        objective_value = solver.solver.Objective().Value()
        best_bound = solver.solver.Objective().BestBound()
        if objective_value != 0:
            gap = abs(objective_value - best_bound) / abs(objective_value)
        else:
            gap = 0.0

        variables = solver.get_solution_variables()
        valid, _ = validate_solution(
            solver.sessions, variables, scheduling_input.classrooms
        )
        solution_valid = valid

    model_stats = mem_after_construct.compare_to(mem_before, "lineno")
    model_mem_kb = sum(s.size_diff for s in model_stats) / 1024

    return BenchmarkResult(
        solver_name="MIP/SCIP",
        scale_label=scale_label,
        num_sessions=len(solver.sessions),
        num_variables=num_vars,
        num_constraints=num_constraints,
        construction_time_s=round(t_construct - t0, 4),
        solve_time_s=round(t_solve - t_construct, 4),
        total_time_s=round(t_solve - t0, 4),
        peak_memory_kb=round(_get_peak_rss_kb(), 1),
        model_memory_kb=round(model_mem_kb, 1),
        status=status,
        objective_value=objective_value,
        optimality_gap=round(gap, 6) if gap is not None else None,
        solution_valid=solution_valid,
    )


# ---------------------------------------------------------------------------
# 4. Real MATF subsets (S / M / L)
# ---------------------------------------------------------------------------

DEFAULT_REAL_SOURCE = "src/algo/input_full_1_semester.json"

SCALE_CONFIGS = {
    "S": {"semesters": [1], "loc_ids": [1], "max_time": 60},
    "M": {"semesters": [1, 3], "loc_ids": [1, 3], "max_time": 60},
    "L": {"semesters": [1, 3, 5, 7], "loc_ids": [1, 2, 3], "max_time": 300},
}

SCALE_LABELS = {
    "S": "MATF-S: 1. godina, lok. Studentski trg",
    "M": "MATF-M: 1-2. godina, lok. Studentski trg + Jagiceva",
    "L": "MATF-L: sve godine, sve lokacije (5 min limit)",
}


def generate_real_subset(
    scheduling_input: SchedulingInput,
    semesters: List[int],
    loc_ids: List[int],
) -> SchedulingInput:
    """Filter a full SchedulingInput to a subset of semesters and locations."""
    return SchedulingInput(
        settings=scheduling_input.settings,
        locations=scheduling_input.locations,
        classrooms=[
            r for r in scheduling_input.classrooms if r.loc_id in loc_ids
        ],
        departments=scheduling_input.departments,
        courses=[
            c for c in scheduling_input.courses if c.semester in semesters
        ],
        students_enrolled=[
            s for s in scheduling_input.students_enrolled
            if s.semester in semesters
        ],
    )


def _resolve_input_path(path: str) -> str:
    """Resolve a file path, trying cwd first then this module's parent dir."""
    if os.path.exists(path):
        return path
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, os.path.basename(path)),
        os.path.join(os.path.dirname(here), os.path.basename(path)),
        os.path.join(here, "..", "..", path),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(
        f"Cannot locate input file '{path}'. Tried: {[path] + candidates}"
    )


def _run_solvers_on_input(
    scheduling_input: SchedulingInput,
    scale_label: str,
    max_time: float,
) -> Tuple[BenchmarkResult, BenchmarkResult]:
    sessions = generate_sessions(scheduling_input, GROUP_SIZE)
    n_sessions = len(sessions)
    n_rooms = len(scheduling_input.classrooms)
    D = len(scheduling_input.settings.working_days)
    H = scheduling_input.settings.end_hour - scheduling_input.settings.start_hour

    print(f"\n{'=' * 65}")
    print(
        f"Scenario: {scale_label} "
        f"({n_sessions} sesija, {n_rooms} ucionica, "
        f"{D} dana x {H} sati)"
    )
    print("=" * 65)

    print("  Pokrece se CP-SAT...", end="", flush=True)
    cp_result = benchmark_cp(scheduling_input, scale_label, max_time)
    print(f" done ({cp_result.status}, {cp_result.total_time_s:.2f}s)")

    print("  Pokrece se MIP/SCIP...", end="", flush=True)
    mip_result = benchmark_mip(scheduling_input, scale_label, max_time)
    print(f" done ({mip_result.status}, {mip_result.total_time_s:.2f}s)")

    print_comparison_table(cp_result, mip_result)
    return cp_result, mip_result


def run_benchmark(
    source_path: str = DEFAULT_REAL_SOURCE,
    scales: Optional[List[str]] = None,
    max_time_override: Optional[float] = None,
) -> List[BenchmarkResult]:
    """Run CP-SAT and MIP/SCIP on real MATF subsets (S, M, L)."""
    if scales is None:
        scales = list(SCALE_CONFIGS.keys())

    resolved = _resolve_input_path(source_path)
    full_input = load_input(resolved)

    results: List[BenchmarkResult] = []
    for scale in scales:
        cfg = SCALE_CONFIGS[scale]
        subset = generate_real_subset(
            full_input, cfg["semesters"], cfg["loc_ids"]
        )
        max_time = max_time_override if max_time_override is not None else cfg["max_time"]
        label = SCALE_LABELS[scale]
        cp_result, mip_result = _run_solvers_on_input(subset, label, max_time)
        results.append(cp_result)
        results.append(mip_result)

    return results


# ---------------------------------------------------------------------------
# 5. Output formatting
# ---------------------------------------------------------------------------

def _fmt_num(n) -> str:
    if n is None:
        return "N/A"
    if isinstance(n, float):
        if n == int(n):
            return f"{int(n):,}"
        return f"{n:,.4f}"
    return f"{n:,}"


def _fmt_pct(v) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:.2f}%"


def _fmt_valid(v) -> str:
    if v is None:
        return "N/A"
    return "PASS" if v else "FAIL"


def print_comparison_table(cp: BenchmarkResult, mip: BenchmarkResult):
    rows = [
        ("Sesije", _fmt_num(cp.num_sessions), _fmt_num(mip.num_sessions)),
        ("Promenljive", _fmt_num(cp.num_variables), _fmt_num(mip.num_variables)),
        ("Ogranicenja", _fmt_num(cp.num_constraints), _fmt_num(mip.num_constraints)),
        ("Vreme konstrukcije", f"{cp.construction_time_s:.4f}s", f"{mip.construction_time_s:.4f}s"),
        ("Vreme resavanja", f"{cp.solve_time_s:.4f}s", f"{mip.solve_time_s:.4f}s"),
        ("Ukupno vreme", f"{cp.total_time_s:.4f}s", f"{mip.total_time_s:.4f}s"),
        ("Model memorija", f"{cp.model_memory_kb:.1f} KB", f"{mip.model_memory_kb:.1f} KB"),
        ("Maksimalna RAM", f"{cp.peak_memory_kb:.0f} KB", f"{mip.peak_memory_kb:.0f} KB"),
        ("Status", cp.status, mip.status),
        ("Objektivna vrednost (max_slot)", _fmt_num(cp.objective_value), _fmt_num(mip.objective_value)),
        ("Optimality gap", _fmt_pct(cp.optimality_gap), _fmt_pct(mip.optimality_gap)),
        ("Resenje validno", _fmt_valid(cp.solution_valid), _fmt_valid(mip.solution_valid)),
    ]

    col0_w = max(len(r[0]) for r in rows)
    col1_w = max(len(r[1]) for r in rows)
    col2_w = max(len(r[2]) for r in rows)
    col1_w = max(col1_w, len("CP-SAT"))
    col2_w = max(col2_w, len("MIP/SCIP"))

    header = (
        f"  {'Metric':<{col0_w}}  "
        f"{'CP-SAT':>{col1_w}}  "
        f"{'MIP/SCIP':>{col2_w}}"
    )
    sep = "  " + "-" * (col0_w + col1_w + col2_w + 4)

    print()
    print(header)
    print(sep)
    for label, cp_val, mip_val in rows:
        print(f"  {label:<{col0_w}}  {cp_val:>{col1_w}}  {mip_val:>{col2_w}}")
    print()


def print_summary(results: List[BenchmarkResult]):
    print("\n" + "=" * 65)
    print("TEORIJSKA KOMPLEKSNOST IZMEDJU CP-SAT I MIP/SCIP")
    print("=" * 65)
    print("""
  CP-SAT (Constraint Programming):
    - Promenljive:   O(S) -- 5 integer promenljive per session
    - Ogranicenja:   kompaktne globalne ogranicenja (AllDifferent, AllowedAssignments)
    - Pretraga:      constraint propagation + lazy-clause SAT pretraga
    - Snaga:    kompaktna model; mocna inferencija skracuje pretragu prostora

  MIP/SCIP (Mixed Integer Programming):
    - Promenljive:   O(S * D * H * R) -- jedna binarna promenljiva per (session, day, hour, room)
    - Ogranicenja: O(D*H*R + G*D*H) linear inequalities
    - Pretraga:      LP relaxation + branch-and-bound
    - Snaga:    LP relaxation daje tesne granice objektivne vrednosti

  Kljucni trade-off:
    CP pravi mali model ali se zavisi od inferencije za skracivanje pretrage.
    MIP pravi veliki model ali dobija jake granice iz LP relaxation.
    Kao problem raste, broj promenljivih MIP eksplodira (multiplikativno),
    dok CP ostaje linearno u broju sesija.
""")


def write_json_report(results: List[BenchmarkResult], path: str):
    data = [asdict(r) for r in results]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"JSON report written to: {path}")


# ---------------------------------------------------------------------------
# 6. CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Merenje CP-SAT vs MIP/SCIP za problem rasporeda ucionica"
    )
    parser.add_argument(
        "--scales",
        nargs="+",
        choices=list(SCALE_CONFIGS.keys()),
        default=None,
        help="Koje MATF podskupove pokrenuti: S, M, L (default: sve)",
    )
    parser.add_argument(
        "--max-time",
        type=float,
        default=None,
        help="Vremenski limit za solver u sekundama (override per-scale defaults).",
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        help="Putanja do JSON fajla za prikazivanje rezultata",
    )
    args = parser.parse_args()

    print("===== Merenje CP-SAT vs MIP/SCIP =====")

    results = run_benchmark(
        scales=args.scales,
        max_time_override=args.max_time,
    )

    print_summary(results)

    if args.json:
        write_json_report(results, args.json)


if __name__ == "__main__":
    main()
