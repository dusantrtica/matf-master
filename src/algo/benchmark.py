import argparse
import copy
import gc
import json
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
from src.algo.data import (
    GROUP_SIZE,
    Session,
    generate_sessions,
    load_input,
    load_staff_input,
)
from src.algo.mip_solver import SimpleMIPSolver
from src.algo.model import Classroom, RuleConfig, SchedulingInput, StaffInput


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
    solution_valid: Optional[bool]


@dataclass
class AnytimeResult:
    """Rezultat jednog pokretanja prosirenog CP modela.

    Pored velicine modela cuva i putanju poboljsanja funkcije cilja kroz
    vreme (`trajectory`), odakle se racunaju vrednosti u zadatim presecima.

    Apsolutne vrednosti cilja nisu uporedive izmedju skala jer veca skala
    ima vise grupa i nastavnika, pa se cilj dodatno normalizuje po sesiji
    i po nastavniku.
    """
    profile: str
    config_name: str
    scale_label: str
    num_sessions: int
    num_teachers: int
    num_variables: int
    num_constraints: int
    construction_time_s: float
    solve_time_s: float
    status: str
    first_solution_time_s: Optional[float]
    first_objective: Optional[float]
    first_objective_per_session: Optional[float]
    first_objective_per_teacher: Optional[float]
    time_to_best_s: Optional[float]
    best_objective: Optional[float]
    best_objective_per_session: Optional[float]
    best_objective_per_teacher: Optional[float]
    best_bound: Optional[float]
    gap_percent: Optional[float]
    solution_valid: Optional[bool]
    trajectory: List[Tuple[float, float, float]]
    checkpoints: Dict[str, Optional[float]]


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
    teacher_time_map: Dict[int, set] = defaultdict(set)
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
        for group_id in session.group_ids:
            if gt_key in group_time_map[group_id]:
                violations.append(
                    f"Kolizija sesije grupe={group_id} "
                    f"dan={d} sat={h} (sesija {s})"
                )
            group_time_map[group_id].add(gt_key)

        if session.teacher_id is not None:
            if gt_key in teacher_time_map[session.teacher_id]:
                violations.append(
                    f"Kolizija nastavnika={session.teacher_id} "
                    f"dan={d} sat={h} (sesija {s})"
                )
            teacher_time_map[session.teacher_id].add(gt_key)

        if session.needs_computers and r not in computer_room_indices:
            violations.append(
                f"Ogranicenje racunara nije zadovoljeno: sesija {s} zahteva racunare "
                f"ali ucionica {r} nema racunara"
            )

    is_valid = len(violations) == 0
    return is_valid, violations


CP_STATUS_NAMES = {
    cp_model.OPTIMAL: "FEASIBLE",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}

# u optimizacionom rezimu razlikujemo dokazano optimalno od samo dopustivog
CP_ANYTIME_STATUS_NAMES = {
    **CP_STATUS_NAMES,
    cp_model.OPTIMAL: "OPTIMAL",
}

MIP_STATUS_NAMES = {
    pywraplp.Solver.OPTIMAL: "FEASIBLE",
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

    solution_valid = None
    if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
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

    solution_valid = None
    if status_code in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
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
        solution_valid=solution_valid,
    )


DEFAULT_REAL_SOURCE = "src/algo/input_full_1_semester.json"

SCALE_CONFIGS = {
    "S": {"semesters": [1], "loc_ids": [1], "max_time": 60},
    "M": {"semesters": [1, 3], "loc_ids": [1, 3], "max_time": 120},
    "L": {"semesters": [1, 3, 5, 7], "loc_ids": [1, 2, 3], "max_time": 600},
}

SCALE_LABELS = {
    "S": "MATF-S: 1. godina, lok. Studentski trg",
    "M": "MATF-M: 1-2. godina, lok. Studentski trg + Jagiceva",
    "L": "MATF-L: sve godine, sve lokacije",
}


def generate_real_subset(
    scheduling_input: SchedulingInput,
    semesters: List[int],
    loc_ids: List[int],
) -> SchedulingInput:
    """Generise podskup realnog inputa filtriranjem po semestru i lokaciji.

    `rules` se namerno ne prenose: poredjenje CP-a i MIP-a radi se nad golim
    modelom (feasibility-only), jer MIP formulacija ne poznaje pravila.
    """
    return SchedulingInput(
        settings=scheduling_input.settings,
        locations=scheduling_input.locations,
        classrooms=[
            r for r in scheduling_input.classrooms if r.loc_id in loc_ids
        ],
        tracks=scheduling_input.tracks,
        courses=[
            c for c in scheduling_input.courses if c.semester in semesters
        ],
        students_enrolled=[
            s for s in scheduling_input.students_enrolled
            if s.semester in semesters
        ],
        groups=[
            g for g in scheduling_input.groups if g.semester in semesters
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
        f"{D} dana x {H} sati, limit {max_time:.0f}s)"
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


# Zavrsna evaluacija prosirenog modela (anytime profil funkcije cilja)
FINAL_SOURCE = "src/algo/input_full_2_semester.json"
FINAL_STAFF_SOURCE = "src/algo/staff_2_semester.json"

# Skaliramo potraznju (godine studija), dok resursi (sve ucionice i
# lokacije) ostaju isti u svim skalama.
FINAL_SCALE_CONFIGS = {
    "S": {"semesters": [2], "max_time": 600},
    "M": {"semesters": [2, 4], "max_time": 600},
    "L": {"semesters": [2, 4, 6, 8], "max_time": 600},
}

FINAL_SCALE_LABELS = {
    "S": "FINAL-S: 1. godina",
    "M": "FINAL-M: 1-2. godina",
    "L": "FINAL-L: sve godine",
}

DEFAULT_CHECKPOINTS = [5, 10, 20, 30, 60, 120, 300, 600]

CONFIG_WITHOUT_STAFF = "bez osoblja"
CONFIG_WITH_STAFF = "sa osobljem"


@dataclass
class FinalProfile:
    """Varijanta instance za zavrsnu evaluaciju.

    Podrazumevani ulaz ima toliko slobodnog prostora (29 ucionica puta 60
    termina) da rezavac optimum dostigne za nekoliko desetina sekundi, pa
    kriva cilja kroz vreme brzo padne na nulu. Zaostreni profil smanjuje
    raspolozive resurse da bi meka pravila stvarno dolazila u sukob.
    """
    name: str
    label: str
    end_hour: Optional[int] = None
    loc_ids: Optional[List[int]] = None
    staff_max_days: Optional[int] = None


FINAL_PROFILES = {
    "realistic": FinalProfile(
        name="realistic",
        label="realno okruzenje (8-20h, sve ucionice)",
    ),
    # 8-14h daje 870 termina za 685 sesija najvece skale (79% popunjenosti).
    # Prostor je namerno biran na ivici: vec pri 720 termina rezavac ne
    # nadje nijedno dopustivo resenje ni za 600s.
    "tight": FinalProfile(
        name="tight",
        label="zaostreno okruzenje (8-14h, najvise 2 radna dana nastavnika)",
        end_hour=14,
        staff_max_days=2,
    ),
}

DEFAULT_PROFILE = "realistic"

# u zaostrenom profilu se sve desava kasnije i sporije, pa gruba mreza
# preseka ne bi uhvatila silazak krive
TIGHT_CHECKPOINTS = [10, 20, 30, 40, 50, 60, 90, 120, 300, 600]


def apply_profile(
    scheduling_input: SchedulingInput,
    staff_input: Optional[StaffInput],
    profile: FinalProfile,
) -> Tuple[SchedulingInput, Optional[StaffInput]]:
    """Primeni profil na (kopiju) instance i ulaza sa osobljem."""
    subset = copy.deepcopy(scheduling_input)
    staff = copy.deepcopy(staff_input) if staff_input is not None else None

    if profile.loc_ids is not None:
        subset.classrooms = [
            c for c in subset.classrooms if c.loc_id in profile.loc_ids
        ]
    if profile.end_hour is not None:
        subset.settings.end_hour = profile.end_hour
    if profile.staff_max_days is not None and staff is not None:
        current = staff.rules.get("staffMaxWorkingDays")
        if current is not None:
            staff.rules["staffMaxWorkingDays"] = RuleConfig(
                enabled=current.enabled,
                penalty=current.penalty,
                params={**current.params, "maxDays": profile.staff_max_days},
            )

    return subset, staff


class ObjectiveTracker(cp_model.CpSolverSolutionCallback):
    """Belezi (vreme, vrednost cilja, donja granica) za svako poboljsanje."""

    def __init__(self, has_objective: bool = True):
        super().__init__()
        self.has_objective = has_objective
        self.trajectory: List[Tuple[float, float, float]] = []

    def on_solution_callback(self):
        if not self.has_objective:
            return
        self.trajectory.append(
            (
                round(self.WallTime(), 4),
                self.ObjectiveValue(),
                self.BestObjectiveBound(),
            )
        )


def objective_at_checkpoints(
    trajectory: List[Tuple[float, float, float]],
    checkpoints: List[int],
) -> Dict[str, Optional[float]]:
    """Stepenasta funkcija: vrednost u trenutku t je cilj poslednjeg
    poboljsanja pronadjenog do tog trenutka (None ako rešenja jos nema)."""
    result: Dict[str, Optional[float]] = {}
    for t in checkpoints:
        best: Optional[float] = None
        for wall_time, objective, _bound in trajectory:
            if wall_time <= t:
                best = objective
            else:
                break
        result[str(t)] = best
    return result


def generate_final_subset(
    scheduling_input: SchedulingInput,
    semesters: List[int],
) -> SchedulingInput:
    """Podskup po godinama studija; sve ucionice i lokacije se zadrzavaju."""
    all_loc_ids = [loc.id for loc in scheduling_input.locations]
    subset = generate_real_subset(scheduling_input, semesters, all_loc_ids)
    # za razliku od poredjenja CP/MIP, ovde se evaluira prosireni model,
    # pa podskup nasledjuje pravila iz punog ulaza
    subset.rules = scheduling_input.rules
    return subset


def _normalize(value: Optional[float], count: int) -> Optional[float]:
    """Cilj po jedinici (sesiji ili nastavniku), za poredjenje skala."""
    if value is None or count <= 0:
        return None
    return round(value / count, 3)


def benchmark_cp_anytime(
    scheduling_input: SchedulingInput,
    staff_input: Optional[StaffInput],
    config_name: str,
    scale_label: str,
    max_time: float,
    checkpoints: List[int],
    profile_name: str = DEFAULT_PROFILE,
) -> AnytimeResult:
    gc.collect()

    t0 = time.perf_counter()
    solver = SimpleCPSolver(
        scheduling_input,
        staff_input=staff_input,
        max_time_seconds=max_time,
        log_progress=False,
    )
    t_construct = time.perf_counter()

    num_vars = len(solver.model.Proto().variables)
    num_constraints = len(solver.model.Proto().constraints)

    has_objective = bool(solver.penalty_vars)
    tracker = ObjectiveTracker(has_objective=has_objective)
    status_code = solver.solve(tracker)
    t_solve = time.perf_counter()

    status = CP_ANYTIME_STATUS_NAMES.get(status_code, str(status_code))
    solved = status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    solution_valid = None
    if solved:
        variables = solver.get_solution_variables()
        valid, _ = validate_solution(
            solver.sessions, variables, scheduling_input.classrooms
        )
        solution_valid = valid

    best_objective = None
    best_bound = None
    gap_percent = None
    if solved and has_objective:
        best_objective = solver.solver.ObjectiveValue()
        best_bound = solver.solver.BestObjectiveBound()
        denominator = max(abs(best_objective), 1.0)
        gap_percent = round(
            100.0 * (best_objective - best_bound) / denominator, 2
        )

    first_solution_time_s = tracker.trajectory[0][0] if tracker.trajectory else None
    first_objective = tracker.trajectory[0][1] if tracker.trajectory else None
    time_to_best_s = tracker.trajectory[-1][0] if tracker.trajectory else None

    num_sessions = len(solver.sessions)
    num_teachers = len(solver.teacher_sessions)

    return AnytimeResult(
        profile=profile_name,
        config_name=config_name,
        scale_label=scale_label,
        num_sessions=num_sessions,
        num_teachers=num_teachers,
        num_variables=num_vars,
        num_constraints=num_constraints,
        construction_time_s=round(t_construct - t0, 4),
        solve_time_s=round(t_solve - t_construct, 4),
        status=status,
        first_solution_time_s=first_solution_time_s,
        first_objective=first_objective,
        first_objective_per_session=_normalize(first_objective, num_sessions),
        first_objective_per_teacher=_normalize(first_objective, num_teachers),
        time_to_best_s=time_to_best_s,
        best_objective=best_objective,
        best_objective_per_session=_normalize(best_objective, num_sessions),
        best_objective_per_teacher=_normalize(best_objective, num_teachers),
        best_bound=best_bound,
        gap_percent=gap_percent,
        solution_valid=solution_valid,
        trajectory=tracker.trajectory,
        checkpoints=objective_at_checkpoints(tracker.trajectory, checkpoints),
    )


def run_final_benchmark(
    source_path: str = FINAL_SOURCE,
    staff_path: str = FINAL_STAFF_SOURCE,
    scales: Optional[List[str]] = None,
    max_time_override: Optional[float] = None,
    checkpoints: Optional[List[int]] = None,
    profile_name: str = DEFAULT_PROFILE,
) -> List[AnytimeResult]:
    """Prosireni CP model na tri skale, sa i bez rasporedjivanja osoblja."""
    if scales is None:
        scales = list(FINAL_SCALE_CONFIGS.keys())
    profile = FINAL_PROFILES[profile_name]
    if checkpoints is None:
        checkpoints = list(
            TIGHT_CHECKPOINTS if profile_name == "tight" else DEFAULT_CHECKPOINTS
        )

    full_input = load_input(_resolve_input_path(source_path))
    full_staff = load_staff_input(_resolve_input_path(staff_path))

    print(f"\nProfil instance: {profile.name} -- {profile.label}")

    results: List[AnytimeResult] = []
    for scale in scales:
        cfg = FINAL_SCALE_CONFIGS[scale]
        base_subset = generate_final_subset(full_input, cfg["semesters"])
        max_time = (
            max_time_override if max_time_override is not None else cfg["max_time"]
        )
        label = FINAL_SCALE_LABELS[scale]

        scale_results = []
        for config_name, staff_source in (
            (CONFIG_WITHOUT_STAFF, None),
            (CONFIG_WITH_STAFF, full_staff),
        ):
            subset, staff = apply_profile(base_subset, staff_source, profile)

            if not scale_results:
                n_rooms = len(subset.classrooms)
                D = len(subset.settings.working_days)
                H = subset.settings.end_hour - subset.settings.start_hour
                print(f"\n{'=' * 65}")
                print(
                    f"Scenario: {label} "
                    f"({n_rooms} ucionica, {D} dana x {H} sati, "
                    f"{n_rooms * D * H} termina, limit {max_time:.0f}s)"
                )
                print("=" * 65)

            print(f"  Pokrece se CP-SAT ({config_name})...", end="", flush=True)
            result = benchmark_cp_anytime(
                subset, staff, config_name, label, max_time, checkpoints,
                profile_name=profile_name,
            )
            print(
                f" done ({result.status}, cilj={_fmt_objective(result.best_objective)}, "
                f"{result.solve_time_s:.2f}s)"
            )
            scale_results.append(result)

        print_final_tables(scale_results, checkpoints)
        results.extend(scale_results)

    print_cross_scale_table(results)
    return results


# Formatiranje i prikaz rezultata
def _fmt_num(n) -> str:
    if n is None:
        return "N/A"
    if isinstance(n, float):
        if n == int(n):
            return f"{int(n):,}"
        return f"{n:,.4f}"
    return f"{n:,}"


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


def _fmt_objective(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if float(value) == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _fmt_seconds(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.2f}s"


def _fmt_ratio(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.3f}"


def _print_rows(rows: List[tuple], headers: tuple):
    widths = [
        max(len(str(headers[i])), max((len(str(r[i])) for r in rows), default=0))
        for i in range(len(headers))
    ]
    header_line = "  " + "  ".join(
        f"{str(h):<{w}}" if i == 0 else f"{str(h):>{w}}"
        for i, (h, w) in enumerate(zip(headers, widths))
    )
    print()
    print(header_line)
    print("  " + "-" * (sum(widths) + 2 * (len(widths) - 1)))
    for row in rows:
        print(
            "  "
            + "  ".join(
                f"{str(c):<{w}}" if i == 0 else f"{str(c):>{w}}"
                for i, (c, w) in enumerate(zip(row, widths))
            )
        )
    print()


def print_final_tables(results: List[AnytimeResult], checkpoints: List[int]):
    """Tabela velicine modela i tabela cilja u zavisnosti od vremena."""
    headers = ("Metrika",) + tuple(r.config_name for r in results)

    size_rows = [
        ("Sesije",) + tuple(_fmt_num(r.num_sessions) for r in results),
        ("Nastavnici",) + tuple(_fmt_num(r.num_teachers) for r in results),
        ("Promenljive",) + tuple(_fmt_num(r.num_variables) for r in results),
        ("Ogranicenja",) + tuple(_fmt_num(r.num_constraints) for r in results),
        (
            "Vreme konstrukcije",
        ) + tuple(f"{r.construction_time_s:.3f}s" for r in results),
        ("Vreme resavanja",) + tuple(f"{r.solve_time_s:.2f}s" for r in results),
        ("Prvo resenje",) + tuple(_fmt_seconds(r.first_solution_time_s) for r in results),
        ("Prvi cilj",) + tuple(_fmt_objective(r.first_objective) for r in results),
        ("Do najboljeg",) + tuple(_fmt_seconds(r.time_to_best_s) for r in results),
        ("Nadjenih resenja",) + tuple(_fmt_num(len(r.trajectory)) for r in results),
        ("Status",) + tuple(r.status for r in results),
        ("Resenje validno",) + tuple(_fmt_valid(r.solution_valid) for r in results),
    ]
    _print_rows(size_rows, headers)

    obj_rows = [
        (f"{t}s",) + tuple(_fmt_objective(r.checkpoints[str(t)]) for r in results)
        for t in checkpoints
    ]
    obj_rows.append(
        ("najbolji cilj",) + tuple(_fmt_objective(r.best_objective) for r in results)
    )
    obj_rows.append(
        ("donja granica",) + tuple(_fmt_objective(r.best_bound) for r in results)
    )
    obj_rows.append(
        (
            "procep",
        ) + tuple(
            "-" if r.gap_percent is None else f"{r.gap_percent:.2f}%"
            for r in results
        )
    )
    _print_rows(obj_rows, ("Vreme",) + tuple(r.config_name for r in results))


def _short_label(result: AnytimeResult) -> str:
    """'FINAL-S: 1. godina' + 'bez osoblja' -> 'FINAL-S/bez'."""
    scale = result.scale_label.split(":")[0].strip()
    config = "bez" if result.config_name == CONFIG_WITHOUT_STAFF else "sa"
    return f"{scale}/{config}"


def print_cross_scale_table(results: List[AnytimeResult]):
    """Medjuskalno poredjenje: apsolutni i normalizovani cilj.

    Apsolutne vrednosti rastu sa skalom prosto zato sto veca instanca ima
    vise grupa i nastavnika, pa se uz njih daje i cilj po sesiji i po
    nastavniku, sto jeste uporedivo izmedju skala.
    """
    if not results:
        return

    print("\n" + "=" * 65)
    print("MEDJUSKALNO POREDJENJE (normalizovan cilj)")
    print("=" * 65)

    headers = ("Metrika",) + tuple(_short_label(r) for r in results)
    rows = [
        ("Sesije",) + tuple(_fmt_num(r.num_sessions) for r in results),
        ("Nastavnici",) + tuple(_fmt_num(r.num_teachers) for r in results),
        ("Prvi cilj",) + tuple(_fmt_objective(r.first_objective) for r in results),
        (
            "Prvi cilj / sesiji",
        ) + tuple(_fmt_ratio(r.first_objective_per_session) for r in results),
        (
            "Prvi cilj / nastavniku",
        ) + tuple(_fmt_ratio(r.first_objective_per_teacher) for r in results),
        ("Najbolji cilj",) + tuple(_fmt_objective(r.best_objective) for r in results),
        (
            "Najbolji cilj / sesiji",
        ) + tuple(_fmt_ratio(r.best_objective_per_session) for r in results),
        (
            "Najbolji cilj / nastavniku",
        ) + tuple(_fmt_ratio(r.best_objective_per_teacher) for r in results),
    ]
    _print_rows(rows, headers)


def print_final_summary(results: List[AnytimeResult]):
    profile_name = results[0].profile if results else DEFAULT_PROFILE
    profile = FINAL_PROFILES[profile_name]
    print("\n" + "=" * 65)
    print("ZAVRSNA EVALUACIJA PROSIRENOG CP MODELA")
    print("=" * 65)
    print(f"""
  Ulaz:       {FINAL_SOURCE}
  Osoblje:    {FINAL_STAFF_SOURCE}
  Profil:     {profile.name} -- {profile.label}
  Skale:      sečenje po godinama studija (semestri 2 / 2,4 / 2,4,6,8)
  Cilj:       tezinska suma prekrsaja mekih pravila
              (procepi u rasporedu grupa, dani preko limita nastavnika)
  Rezim:      OPTIMIZACIJA -- prati se vrednost cilja kroz vreme
""")
    for r in results:
        print(
            f"  {r.scale_label} [{r.config_name}]: "
            f"prvo resenje {_fmt_seconds(r.first_solution_time_s)} "
            f"(cilj {_fmt_objective(r.first_objective)}), "
            f"nadjenih resenja: {len(r.trajectory)}, "
            f"najbolji cilj: {_fmt_objective(r.best_objective)} "
            f"u {_fmt_seconds(r.time_to_best_s)} [{r.status}]"
        )
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
    - Ogranicenja:   O(D*H*R + G*D*H) linear inequalities
    - Pretraga:      LP relaxation + branch-and-bound
    - Snaga:    LP relaxation daje tesne granice objektivne vrednosti

  Rezim:      FEASIBILITY-ONLY (bez funkcije cilja)
  Cilj je naci bilo koji validan raspored.
""")


def write_json_report(results: List, path: str):
    # pod bazel-om je radni direktorijum runfiles, pa relativne putanje
    # razresavamo u odnosu na koren radnog prostora
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if workspace and not os.path.isabs(path):
        path = os.path.join(workspace, path)

    data = [asdict(r) for r in results]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"JSON report written to: {path}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Merenje modela rasporeda: poredjenje CP-SAT vs MIP/SCIP "
            "(feasibility-only) i zavrsna evaluacija prosirenog CP modela"
        )
    )
    parser.add_argument(
        "--mode",
        choices=["compare", "final", "all"],
        default="compare",
        help=(
            "compare: CP-SAT vs MIP/SCIP (glava o evaluaciji); "
            "final: prosireni CP model sa i bez osoblja; all: oba"
        ),
    )
    parser.add_argument(
        "--scales",
        nargs="+",
        choices=list(SCALE_CONFIGS.keys()),
        default=None,
        help="Koje podskupove pokrenuti: S, M, L (default: sve)",
    )
    parser.add_argument(
        "--max-time",
        type=float,
        default=None,
        help="Vremenski limit za solver u sekundama (override per-scale defaults).",
    )
    parser.add_argument(
        "--profile",
        choices=list(FINAL_PROFILES.keys()),
        default=DEFAULT_PROFILE,
        help=(
            "Profil instance za --mode final. "
            + "; ".join(f"{p.name}: {p.label}" for p in FINAL_PROFILES.values())
        ),
    )
    parser.add_argument(
        "--checkpoints",
        nargs="+",
        type=int,
        default=None,
        help=(
            "Vremenski preseci (u sekundama) u kojima se ocitava vrednost "
            f"funkcije cilja (default: {' '.join(map(str, DEFAULT_CHECKPOINTS))})"
        ),
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        help="Putanja do JSON fajla za rezultate poredjenja CP vs MIP",
    )
    parser.add_argument(
        "--final-json",
        type=str,
        default=None,
        help="Putanja do JSON fajla za rezultate zavrsne evaluacije",
    )
    args = parser.parse_args()

    if args.mode in ("compare", "all"):
        print("===== Merenje CP-SAT vs MIP/SCIP (feasibility-only) =====")
        results = run_benchmark(
            scales=args.scales,
            max_time_override=args.max_time,
        )
        print_summary(results)
        if args.json:
            write_json_report(results, args.json)

    if args.mode in ("final", "all"):
        print("===== Zavrsna evaluacija prosirenog CP modela =====")
        final_results = run_final_benchmark(
            scales=args.scales,
            max_time_override=args.max_time,
            checkpoints=args.checkpoints,
            profile_name=args.profile,
        )
        print_final_summary(final_results)
        if args.final_json:
            write_json_report(final_results, args.final_json)


if __name__ == "__main__":
    main()
