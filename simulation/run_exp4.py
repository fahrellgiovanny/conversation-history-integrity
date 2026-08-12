#!/usr/bin/env python3
"""run_exp4 - EXP-4: multi-agent memory (the pre-registered protocol rev. 4).

Simulated agent A -> agent B memory passing. A runs turns 1-7 and hands a
serialized history blob + stored digest to B; B verifies at ingestion and
continues turns 8-15. Conditions (n=20 each, Gemini):
  clean       : blob intact -> 0 flags, B continues
  midtransfer : blob mutated between A and B -> flag at B's ingestion
  store       : B stores, then stored state mutated -> flag at B's next verify

Gate: 0 flags on clean; pooled tampered (b+c, n=40) Wilson LB >= 0.90
(0.912 at 40/40); 100% observed is the deterministic point-expectation.

Usage:
  python3 run_exp4.py --condition clean
  python3 run_exp4.py            # all conditions (resume on)
  python3 run_exp4.py --dry
"""

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domains import CASES  # noqa: E402
from lib import config  # noqa: E402
from lib.api import call_with_retry, get_model, needs_key  # noqa: E402
from lib.resume import (make_writer, ProgressReporter, purge_error_sessions, run_tasks_per_model, scan_completed)  # noqa: E402
from lib.session import clean_prompt, make_row, serialize_log  # noqa: E402
from verify_stack.mechanisms import M1Hash  # noqa: E402

TAG = "exp4"
HANDOFF_TURN = 8


def build_tasks(condition: str) -> list:
    counts = config.per_case_counts(config.EXP4["n"])
    tasks = []
    for case in config.CASES:
        for run in range(1, counts[case] + 1):
            tasks.append({
                "condition": condition, "model": config.MODEL_GEMINI,
                "case": case, "run": run,
                "session_id": f"exp4_{condition}_{case}_{run:03d}",
            })
    return tasks


def run_condition(model, task: dict, dry: bool) -> list:
    case = CASES[task["case"]]
    condition = task["condition"]
    real = {}
    log = []
    rows = []

    def call(prompt):
        res = call_with_retry(model, prompt)
        real[len(real) + 1] = res["rawOutput"]
        log.append(f"User: {prompt}\nAssistant: {res['rawOutput']}")
        return res

    def record(turn, ev, res):
        rows.append(make_row(
            session_id=task["session_id"], exp="EXP-4", cell=condition,
            model=task["model"], protocol="A", case_id=case.case_id,
            mechanism="M1", condition=condition, run=task["run"], turn=turn,
            ev=ev, res=res))

    # --- Phase 1: agent A, turns 1-7 (clean, protocol A framing) ---
    tier_a = M1Hash()
    tier_a.begin_session()
    for turn in range(1, HANDOFF_TURN):
        prompt = clean_prompt(case, "A", turn, real)
        ev = tier_a.check(serialize_log(log))
        res = call(prompt)
        tier_a.observe(serialize_log(log))
        record(turn, ev, res)

    # --- Handoff blob: serialized history + stored digest ---
    blob = serialize_log(log)
    stored_digest = tier_a._stored_digest

    # --- Phase 2: transfer tampering (mid-transfer condition) ---
    ingested = blob
    if condition == "midtransfer":
        ingested = blob.replace("Assistant: ", "Assistant: [forged] ", 1)

    # --- Agent B ingestion (turn 8): verify blob vs transferred digest ---
    # "store" condition: transfer is intact, so ingestion PASSES; the attack
    # mutates B's STORED state afterwards (detected at the next verification).
    tier_b = M1Hash()
    tier_b.begin_session()
    tier_b._stored_digest = stored_digest
    tier_b._last_clean = blob

    ev = tier_b.check(ingested)
    prompt = clean_prompt(case, "A", HANDOFF_TURN, real)
    res = call(prompt)
    tier_b.observe(serialize_log(log))
    record(HANDOFF_TURN, ev, res)

    if condition == "store":
        # Attack at B's store: mutate the stored history in place; the next
        # verification (turn 9) must flag. Restore-and-log after the flag.
        clean_last = log[-1]
        log[-1] = clean_last.replace("Assistant: ", "Assistant: [forged] ", 1)

    # --- Agent B continues turns 9-15 ---
    for turn in range(HANDOFF_TURN + 1, config.TURNS + 1):
        ev = tier_b.check(serialize_log(log))
        if condition == "store" and ev["flagged"] and "forged" in log[-1]:
            log[-1] = clean_last
        prompt = clean_prompt(case, "A", turn, real)
        res = call(prompt)
        tier_b.observe(serialize_log(log))
        record(turn, ev, res)

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-4: multi-agent memory")
    parser.add_argument("--condition", choices=config.EXP4["conditions"] + ["all"],
                        default="all")
    parser.add_argument("--workers", type=int, default=config.WORKERS)
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    conditions = (config.EXP4["conditions"] if args.condition == "all"
                  else [args.condition])
    tasks = [t for c in conditions for t in build_tasks(c)]
    done = scan_completed(TAG)
    todo = [t for t in tasks if t["session_id"] not in done]

    print(f"=== EXP-4 multi-agent memory ===  dry={args.dry} workers={args.workers}")
    print(f"Conditions: {conditions}  total: {len(tasks)}  done: "
          f"{len(tasks)-len(todo)}  to run: {len(todo)}")
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
        rows = run_condition(model, task, args.dry)
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

    for cond in conditions:
        rows = [r for r in all_rows if r["cell"] == cond]
        if cond == "clean":
            flags = sum(int(r["flagged"]) for r in rows)
            print(f"\nEXP-4 {cond}: {flags} flags across {len(rows)} rows "
                  f"(gate: 0 flags)")
        else:
            # Tampered conditions: flag expected at the first verification
            # after the attack (ingestion turn 8 for midtransfer, turn 9 for
            # store). Count per-session detection at any post-handoff turn.
            post = [r for r in rows if int(r["turn"]) >= HANDOFF_TURN]
            flagged_sessions = set(r["session_id"] for r in post if int(r["flagged"]))
            n_sessions = len(set(r["session_id"] for r in rows))
            print(f"\nEXP-4 {cond}: detection {len(flagged_sessions)}/{n_sessions} "
                  f"post-handoff (pooled b+c gate: Wilson LB >= 0.90)")
    print("\nNext: python3 run_exp5.py")


if __name__ == "__main__":
    main()
