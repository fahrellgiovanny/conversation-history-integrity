#!/usr/bin/env python3
"""run_exp3 - EXP-3: overhead, paired same-day sub-study (SIMULATION_PAPER3 rev. 4).

30 stack-off twin sessions (15 Gemini + 15 GLM) re-running a fixed random
subsample of EXP-1c sessions' turn prompts on the same day, with the verify
stack bypassed. The defended latency comes from the EXP-1c CSVs (latency_ms
column); the stack-off latency is measured here; the paired per-turn delta
is the overhead quantity (median < 5% per model is the gate).

Prereq: EXP-1c rows must exist in output/integrity/exp1_*.csv. In --dry mode a
synthetic EXP-1c source is generated.

Usage:
  python3 run_exp3.py             # real run (after EXP-1)
  python3 run_exp3.py --dry       # offline verification
"""

import argparse
import csv
import hashlib
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from integritylib import config  # noqa: E402
from integritylib.api import call_with_retry, get_model, needs_key  # noqa: E402
from integritylib.resume import BatchWriter, ProgressReporter, purge_error_sessions, run_tasks_per_model, scan_completed  # noqa: E402
from integritylib.session import make_row  # noqa: E402

TAG = "exp3"


def load_exp1c_rows() -> dict:
    """session_id -> metadata + [(turn, raw_output)] from EXP-1c batches.

    Prompts are NOT stored in the unified schema; they are reconstructed
    deterministically (temperature 0, same build functions) from the stored
    raw outputs, so the stack-off twin re-sends byte-identical prompts.
    """
    out = {}
    if not config.OUTPUT_DIR.exists():
        return out
    for f in sorted(config.OUTPUT_DIR.glob("exp1_batch_*.csv")):
        with open(f, newline="", encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                if r.get("cell") != "1c":
                    continue
                out.setdefault(r["session_id"], {
                    "model": r["model"], "protocol": r["protocol"],
                    "case": r["case"], "turns": [],
                })
                out[r["session_id"]]["turns"].append(
                    (int(r["turn"]), r.get("raw_output", "")))
    return out


def synthetic_exp1c() -> dict:
    """Dry-mode stand-in: one fake EXP-1c session per model (session_id
    formatted like real EXP-1c ids so pick_pairs parses the model)."""
    def fake(model):
        return {"model": model, "protocol": "A", "case": "math_short",
                "turns": [(t, f"DRY_RAW_{t}") for t in range(1, 16)]}
    return {f"exp1_1c_{config.MODEL_GEMINI}_A_math_short_001": fake(config.MODEL_GEMINI),
            f"exp1_1c_{config.MODEL_GLM}_A_math_short_001": fake(config.MODEL_GLM)}


def pick_pairs(source: dict) -> list:
    """Deterministic subsample: 15 sessions per model from EXP-1c."""
    by_model = {}
    for sid in source:
        model = sid.split("_")[2]
        by_model.setdefault(model, []).append(sid)
    picked = []
    for model, sids in by_model.items():
        ordered = sorted(sids)
        seed = int(hashlib.sha256(f"exp3:{model}".encode()).hexdigest()[:8], 16)
        n = min(config.EXP3_PAIRS_PER_MODEL, len(ordered))
        for i in range(n):
            idx = (seed + i * 7) % len(ordered)
            sid = ordered[idx]
            picked.append({"model": model, "source_id": sid,
                           "session_id": f"exp3_off_{sid}"})
    return picked


def run_pair(model, pair: dict, meta: dict) -> list:
    """Re-run the twin session with the verify stack bypassed, re-sending
    byte-identical prompts (reconstructed deterministically from the stored
    raw outputs of the defended session)."""
    from domains import CASES
    from integritylib.session import clean_prompt
    case = CASES[meta["case"]]
    real = {}
    rows = []
    for turn, raw in sorted(meta["turns"]):
        prompt = clean_prompt(case, meta["protocol"], turn, real)
        real[turn] = raw
        res = call_with_retry(model, prompt)
        rows.append(make_row(
            session_id=pair["session_id"], exp="EXP-3", cell="paired_off",
            model=pair["model"], protocol=meta["protocol"], case_id=meta["case"],
            mechanism="M1", condition="stack_off", run=0, turn=turn,
            ev={"flagged": False, "tier": "", "blocking_layer": None,
                "restored": False, "utility_impact": 0.0},
            res=res, pair_id=pair["source_id"]))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-3: paired overhead sub-study")
    parser.add_argument("--workers", type=int, default=config.WORKERS)
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    source = synthetic_exp1c() if args.dry else load_exp1c_rows()
    if not source:
        print("No EXP-1c rows found in output/integrity/. Run EXP-1 cell 1c first "
              "(or use --dry).")
        return

    pairs = pick_pairs(source)
    done = scan_completed(TAG)
    todo = [p for p in pairs if p["session_id"] not in done]

    print(f"=== EXP-3 paired overhead ===  dry={args.dry} workers={args.workers}")
    print(f"Pairs: {len(pairs)} ({config.EXP3_PAIRS_PER_MODEL} per model)  "
          f"done: {len(pairs)-len(todo)}  to run: {len(todo)}")
    if not todo:
        print("Nothing to run (resume: all sessions complete).")
        return
    if not args.dry:
        for t in todo:
            needs_key(t["model"])

    writer = BatchWriter(TAG)
    reporter = ProgressReporter(len(todo), TAG)
    reporter.start()
    lock = threading.Lock()

    def worker(pair):
        model = get_model(pair["model"], args.dry)
        meta = source[pair["source_id"]]
        rows = run_pair(model, pair, meta)
        with lock:
            reporter.tick()
            writer.add(rows)
        return len(rows)

    failed = run_tasks_per_model(todo, worker, workers_per_model=args.workers)
    if failed:
        print(f"  {failed} tasks failed (will be handled at batch-end rerun)")

    reporter.stop = True
    total = writer.finish()
    purge_error_sessions(TAG)
    print(f"\nDONE: {total} rows written to output/integrity/{TAG}_*.csv")
    print("Analysis: pair exp3 (stack_off) vs exp1c (stack_on) per-turn latency "
          "deltas, median < 5% per model is the gate (pre_registration.md).")
    print("\nNext: python3 run_exp4.py")


if __name__ == "__main__":
    main()
