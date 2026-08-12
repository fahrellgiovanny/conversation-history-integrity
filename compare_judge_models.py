#!/usr/bin/env python3
"""compare_judge_models.py - decide the primary judge empirically.

Runs deepseek-v4-pro and deepseek-v4-flash on the SAME sample of the conversation-history integrity batches
turns and reports: cross-judge agreement (kappa on T1/T2), disagreement
examples, per-model measured token usage, latency, and error rates.

Usage:
  python3 compare_judge_models.py --sessions 15   # per cell sample size
Requires DEEPSEEK_API_KEY.
"""

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Import the judge directly (a separate instance from run_judge's late import).
import lib.judge as judge_mod  # noqa: E402
from lib.judge import call_judge  # noqa: E402
import run_judge as rj  # noqa: E402

OUT = SCRIPT_DIR / "output" / "judge_model_compare.csv"

MODELS = ["deepseek-v4-pro", "deepseek-v4-flash"]

# adoption-relevant cells for the sample
SAMPLE_CELLS = ["1c", "l2a_forged", "l2b_forged", "main_A", "main_B", "salami"]


def sample_sessions(per_cell: int) -> list:
    """Deterministic sample: first per_cell sessions per cell (gemini only)."""
    sessions = rj.load_rows()
    picked = []
    seen = Counter()
    for sid in sorted(sessions):
        rows = sessions[sid]
        cell = rows[min(rows.keys())].get("cell", "")
        model = rows[min(rows.keys())].get("model", "")
        if cell in SAMPLE_CELLS and model == "gemini-3.1-flash-lite" and seen[cell] < per_cell:
            seen[cell] += 1
            for turn in sorted(rows):
                if turn >= 5:
                    picked.append((sid, turn))
    return picked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=15)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()

    todo = sample_sessions(args.sessions)
    sessions = rj.load_rows()
    print(f"Sample: {len(todo)} turns from {args.sessions} sessions x "
          f"{len(SAMPLE_CELLS)} cells, judged by BOTH models "
          f"({len(todo)*2} calls)")

    results = []
    err = Counter()
    lat = {m: [] for m in MODELS}
    t0 = time.time()

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def one(item):
        sid, turn = item
        row = sessions[sid][turn]
        case = rj.CASES.get(row["case"])
        context = rj.rebuild_prompt(
            row, {t: sessions[sid][t].get("raw_output", "") for t in sessions[sid]},
            case) if case is not None else ""
        rec = {"sid": sid, "turn": turn, "cell": row.get("cell", "")}
        for m in MODELS:
            judge_mod.MODEL = m
            t_start = time.time()
            t1, t2, just = call_judge(row["case"], context, row.get("raw_output", ""))
            lat[m].append(time.time() - t_start)
            if t1 is None:
                err[m] += 1
                rec[f"{m}_t1"], rec[f"{m}_t2"], rec[f"{m}_just"] = None, None, just[:100]
            else:
                rec[f"{m}_t1"], rec[f"{m}_t2"], rec[f"{m}_just"] = t1, t2, just[:100]
        return rec

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for rec in ex.map(one, todo):
            results.append(rec)

    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    A, B = MODELS
    pairs_t1 = [(r[f"{A}_t1"], r[f"{B}_t1"]) for r in results
                if r[f"{A}_t1"] is not None and r[f"{B}_t1"] is not None]
    pairs_t2 = [(r[f"{A}_t2"], r[f"{B}_t2"]) for r in results
                if r[f"{A}_t2"] is not None and r[f"{B}_t2"] is not None]

    def kappa(pairs):
        n = len(pairs)
        if n == 0:
            return float("nan")
        po = sum(1 for a, b in pairs if a == b) / n
        ca = Counter(a for a, _ in pairs)
        cb = Counter(b for _, b in pairs)
        pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
        return (po - pe) / (1 - pe) if pe < 1 else 1.0

    k1, k2 = kappa(pairs_t1), kappa(pairs_t2)
    agree1 = sum(1 for a, b in pairs_t1 if a == b) / len(pairs_t1) if pairs_t1 else 0
    agree2 = sum(1 for a, b in pairs_t2 if a == b) / len(pairs_t2) if pairs_t2 else 0
    t_avg = {m: sum(v) / len(v) for m, v in lat.items() if v}

    print(f"\n=== CROSS-JUDGE AGREEMENT (n={len(results)} turns) ===")
    print(f"  T1 (adoption): agreement {agree1*100:.1f}%  kappa {k1:.3f}")
    print(f"  T2 (severity): agreement {agree2*100:.1f}%  kappa {k2:.3f}")
    print(f"\n=== ERROR RATE ===")
    for m in MODELS:
        print(f"  {m}: {err[m]}/{len(results)} unparseable")
    print(f"\n=== LATENCY (per call) ===")
    for m in MODELS:
        print(f"  {m}: {t_avg.get(m, 0):.2f}s")
    print(f"\n=== SAMPLE DISAGREEMENTS (T1) ===")
    shown = 0
    for r in results:
        if r[f"{A}_t1"] != r[f"{B}_t1"] and shown < 5:
            print(f"  {r['sid']} t{r['turn']} ({r['cell']}): {A}={r[f'{A}_t1']} "
                  f"({r[f'{A}_just'][:60]}) | {B}={r[f'{B}_t1']} ({r[f'{B}_just'][:60]})")
            shown += 1
    print(f"\nTotal time: {time.time()-t0:.0f}s. Details -> {OUT}")


if __name__ == "__main__":
    main()
