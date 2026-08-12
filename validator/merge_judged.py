#!/usr/bin/env python3
"""merge_judged.py - apply judged.csv scores into the exp batch rows.

After the judge pass writes output/judged.csv, this merges
t1_adoption/t2_severity back into the unified batch CSVs so every
downstream consumer (exp7c ASV/MR, tables, analysis) sees the
scores. Without this step, batches keep PILOT_NO_JUDGE forever and
exp7c's ASV/MR never computes.

Idempotent (re-running is a no-op); rewrites batches atomically.
Rows without a judge score (failed judge) are left untouched.

Usage:
  python3 merge_judged.py
"""

import csv
import sys
from pathlib import Path

csv.field_size_limit(2**31 - 1)
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "simulation"))

from lib.config import OUTPUT_DIR  # noqa: E402
from lib.session import SESSION_SCHEMA  # noqa: E402

JUDGED = OUTPUT_DIR / "judged.csv"


def main() -> None:
    if not JUDGED.exists():
        print("judged.csv not found - run run_judge.py first.")
        return

    scores = {}
    with open(JUDGED, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            scores[(r["session_id"], int(r["turn"]))] = r

    merged = 0
    files = sorted(OUTPUT_DIR.glob("exp*_batch_*.csv"))
    for f in files:
        with open(f, newline="", encoding="utf-8", errors="replace") as fh:
            rows = [r for r in csv.DictReader(fh)]
        if not rows:
            continue
        changed = 0
        for r in rows:
            key = (r.get("session_id"), int(r.get("turn") or 0))
            s = scores.get(key)
            if s is not None and s.get("t1_adoption") not in ("", "PILOT_NO_JUDGE"):
                r["t1_adoption"] = s["t1_adoption"]
                r["t2_severity"] = s["t2_severity"]
                changed += 1
        if changed:
            tmp = f.with_suffix(".csv.tmp")
            with open(tmp, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=SESSION_SCHEMA)
                w.writeheader()
                for r in rows:
                    w.writerow({k: r.get(k, "") for k in SESSION_SCHEMA})
            tmp.replace(f)
            merged += changed
            print(f"  {f.name}: {changed} rows updated")

    print(f"\nMerged {merged} judge scores into {len(files)} batch files.")
    print("exp7c ASV/MR and tables adoption columns now have real scores.")


if __name__ == "__main__":
    main()
