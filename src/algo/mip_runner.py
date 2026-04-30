import argparse
import os
import sys
import time

from ortools.linear_solver import pywraplp

from src.algo.data import load_input, GROUP_SIZE, Session
from src.algo.mip_solver import SimpleMIPSolver
from src.algo.model import SchedulingInput
from src.algo.report import export_schedule_to_excel


def print_table(rows, headers):
    cols = len(headers)
    col_widths = [
        max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]
    format_str = " | ".join(['{:<%d}' % w for w in col_widths])
    header_line = format_str.format(*headers)
    sep_line = '-+-'.join(['-' * w for w in col_widths])
    print(header_line)
    print(sep_line)
    for row in rows:
        print(format_str.format(*row))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MIP schedule solver")
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print the full schedule table to the terminal",
    )
    args = parser.parse_args()

    input_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input.json")

    print("Loading input...", flush=True)
    scheduling_input: SchedulingInput = load_input(input_path)
    print(f"Loaded {len(scheduling_input.courses)} courses, "
          f"{len(scheduling_input.classrooms)} rooms", flush=True)

    print("Creating MIP solver (300s limit)...", flush=True)
    solver = SimpleMIPSolver(scheduling_input, max_time_seconds=300.0)
    print(f"Model has {len(solver.sessions)} sessions to schedule.", flush=True)

    print("Solving...", flush=True)
    t_start = time.perf_counter()
    status = solver.solve()
    elapsed = time.perf_counter() - t_start

    status_map = {
        pywraplp.Solver.OPTIMAL: "OPTIMAL",
        pywraplp.Solver.FEASIBLE: "FEASIBLE",
        pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
        pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
        pywraplp.Solver.ABNORMAL: "ABNORMAL",
        pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
    }
    status_name = status_map.get(status, f"UNKNOWN({status})")
    print(f"\nSolver finished with status: {status_name}", flush=True)
    print(f"MIP solver completed in {elapsed:.2f}s", flush=True)

    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        print("No feasible solution found.")
        sys.exit(2)

    variables = solver.get_solution_variables()
    if not variables:
        print("No assignment found.")
        sys.exit(2)

    if args.verbose:
        headers = ["Session", "Group", "Department", "Course", "SessionType",
                   "NeedsComputers", "Day", "Hour", "Room"]
        rows = []
        day_list = scheduling_input.settings.working_days
        classroom_id_map = {i: c for i, c in enumerate(scheduling_input.classrooms)}
        courses_id_map = {c.id: c for c in scheduling_input.courses}

        for v, session in zip(variables, solver.sessions):
            room = classroom_id_map.get(v["room"])
            course = courses_id_map.get(session.course_id)
            row = [
                session.id,
                session.group_id,
                session.department_id,
                course.name if course else session.course_id,
                session.session_type,
                'YES' if session.needs_computers else 'NO',
                day_list[v["day"]],
                v["hour"] + scheduling_input.settings.start_hour,
                f"{room.name} (id={room.id})" if room else v["room"],
            ]
            rows.append(row)

        print_table(rows, headers)

    workspace_dir = os.environ.get("BUILD_WORKSPACE_DIRECTORY", os.getcwd())
    out_dir = os.path.join(workspace_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    excel_path = os.environ.get(
        "SCHEDULE_OUTPUT",
        os.path.join(out_dir, "mip_schedule.xlsx"),
    )
    export_schedule_to_excel(solver, scheduling_input, excel_path)
    print(f"\nExcel schedule exported to: {excel_path}", flush=True)
