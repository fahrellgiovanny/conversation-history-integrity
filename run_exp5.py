#!/usr/bin/env python3
"""run_exp5 - EXP-5: comparative harness, M1-M7 (the pre-registered protocol rev. 4).

Main matrix: 7 mechanisms x protocols {A, C} x models {Gemini, GLM} x n=30
= 840 sessions. Clean-FP subset: M4-M7 x 2 models x n=10 clean-history
sessions = 80 sessions (classic defenses are semantic; their clean FPs are
measured, never assumed; crypto clean FP is deterministic-zero per Lemma 1).

Delivery semantics:
  M1-M3 on A : retroactive history mutation -> flag + restore (fail-closed)
  M1-M3 on C : must-pass side; no mutation -> no flag (layer-determinism)
  M4-M7 on A : baseline presentation (turn-4 substitution); filter transforms
  M4-M7 on C : override in current prompt; filter detects + transforms
  clean subset: neutral questions only; filters must stay silent

Usage:
  python3 run_exp5.py --mech M4 --protocol A
  python3 run_exp5.py                     # full matrix (resume on)
  python3 run_exp5.py --dry
"""

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from domains import CASES  # noqa: E402
from lib import config  # noqa: E402
from lib.api import call_with_retry, get_model, needs_key  # noqa: E402
from lib.report import print_detection, print_fp  # noqa: E402
from lib.resume import (make_writer, ProgressReporter, purge_error_sessions, run_tasks_per_model, scan_completed)  # noqa: E402
from lib.session import SessionRunner  # noqa: E402
from verify_stack.mechanisms import make_mechanism  # noqa: E402

TAG = "exp5"
CRYPTO = ("M1", "M2", "M3")


def build_tasks(mech: str, protocol: str) -> list:
    spec = config.EXP5
    tasks = []
    counts = config.per_case_counts(spec["n"])
    for model in spec["models"]:
        for case in config.CASES:
            for run in range(1, counts[case] + 1):
                tasks.append({
                    "mech": mech, "protocol": protocol, "model": model,
                    "case": case, "run": run, "clean": False,
                    "session_id": f"exp5_{mech}_{protocol}_{model}_{case}_{run:03d}",
                })
    return tasks


def build_clean_tasks(mech: str) -> list:
    spec = config.EXP5["clean_subset"]
    counts = config.per_case_counts(spec["n"])
    tasks = []
    for model in spec["models"]:
        for case in config.CASES:
            for run in range(1, counts[case] + 1):
                tasks.append({
                    "mech": mech, "protocol": "B", "model": model,
                    "case": case, "run": run, "clean": True,
                    "session_id": f"exp5_clean_{mech}_{model}_{case}_{run:03d}",
                })
    return tasks


def run_one(model, task: dict, dry: bool) -> list:
    case = CASES[task["case"]]
    mech = make_mechanism(task["mech"])
    runner = SessionRunner(mech, lambda p: call_with_retry(model, p), dry=dry)

    if task["clean"]:
        neutral = case.turns.get(6, "")
        rows = runner.run_filter_session(
            case, task["protocol"], session_id=task["session_id"],
            exp="EXP-5", cell="clean_subset", model=task["model"],
            run=task["run"], mechanism_label=task["mech"],
            condition="clean", turn5_override=neutral)
        return rows

    if task["mech"] in CRYPTO:
        attack = "mutation" if task["protocol"] == "A" else "none"
        return runner.run_history_session(
            case, task["protocol"], session_id=task["session_id"],
            exp="EXP-5", cell=f"main_{task['protocol']}", model=task["model"],
            run=task["run"], attack=attack, mechanism_label=task["mech"],
            condition=f"{task['mech']}_{task['protocol']}")
    else:
        return runner.run_filter_session(
            case, task["protocol"], session_id=task["session_id"],
            exp="EXP-5", cell=f"main_{task['protocol']}", model=task["model"],
            run=task["run"], mechanism_label=task["mech"],
            condition=f"{task['mech']}_{task['protocol']}",
            use_baseline_prompt=(task["protocol"] == "A"))


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-5: comparative harness")
    parser.add_argument("--mech", choices=config.EXP5["mechanisms"] + ["all"],
                        default="all")
    parser.add_argument("--protocol", choices=["A", "C", "all"], default="all")
    parser.add_argument("--workers", type=int, default=config.WORKERS)
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--model", choices=["gemini", "glm", "all"], default="all",
                        help="restrict to one model family (e.g. run the Gemini "
                             "half while GLM quota is constrained)")
    args = parser.parse_args()

    mechs = (config.EXP5["mechanisms"] if args.mech == "all" else [args.mech])
    protocols = (config.EXP5["protocols"] if args.protocol == "all"
                 else [args.protocol])
    wanted_models = {"gemini": [config.MODEL_GEMINI], "glm": [config.MODEL_GLM],
                     "all": config.EXP5["models"]}[args.model]

    tasks = []
    for m in mechs:
        for p in protocols:
            tasks.extend([t for t in build_tasks(m, p)
                          if t["model"] in wanted_models])
        if m in config.EXP5["clean_subset"]["mechanisms"] and args.protocol == "all":
            tasks.extend([t for t in build_clean_tasks(m)
                          if t["model"] in wanted_models])

    done = scan_completed(TAG)
    todo = [t for t in tasks if t["session_id"] not in done]

    print(f"=== EXP-5 comparative harness ===  dry={args.dry} workers={args.workers}")
    print(f"Mechanisms: {mechs}  protocols: {protocols}  total: {len(tasks)}  "
          f"done: {len(tasks)-len(todo)}  to run: {len(todo)}")
    if not todo:
        print("Nothing to run (resume: all sessions complete).")
        return
    if not args.dry:
        for t in todo:
            needs_key(t["model"])

    writer = make_writer(TAG, args.dry)
    reporter = ProgressReporter(len(todo), TAG)
    reporter.start()
    lock = threading.Lock()

    def worker(task):
        model = get_model(task["model"], args.dry)
        rows = run_one(model, task, args.dry)
        with lock:
            reporter.tick()
            writer.add(rows)
        return len(rows)

    failed = run_tasks_per_model(todo, worker, workers_per_model=args.workers)
    if failed:
        print(f"  {failed} tasks failed (will be handled at batch-end rerun)")

    reporter.stop = True
    total = writer.finish()
    if not args.dry:
        purge_error_sessions(TAG)
    print(f"\nDONE: {total} rows generated "
          f"({'dry - nothing written' if args.dry else f'written to output/{TAG}_*.csv'})")

    import csv as _csv
    all_rows = []
    for f in sorted(config.OUTPUT_DIR.glob(f"{TAG}_*.csv")):
        with open(f, newline="", encoding="utf-8", errors="replace") as fh:
            all_rows.extend([r for r in _csv.DictReader(fh)])

    main_rows = [r for r in all_rows if r["cell"].startswith("main_")]
    print_detection(main_rows, "EXP-5 detection (turn 5, protocol A cells)")
    clean_rows = [r for r in all_rows if r["cell"] == "clean_subset"]
    print_fp(clean_rows, "EXP-5 clean-FP subset (M4-M7; gate: measured, reported)")
    print("\nNext: python3 run_exp6.py")


if __name__ == "__main__":
    main()
