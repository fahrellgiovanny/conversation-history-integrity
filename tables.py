#!/usr/bin/env python3
"""tables - generate the 5 paper tables from batches + judged.csv.

Reads output/exp*_batch_*.csv and output/judged.csv and
produces the paper-ready tables of the pre-registration section 5:
  Table 1: Detection/FP audit (EXP-1a/1b/1d + sentinel) - judge-free
  Table 2: Adoption reduction (EXP-1c) vs the reference pipeline baseline labels
  Table 3: Comparative harness ranking (EXP-5, the core artifact)
  Table 4: Overhead (EXP-3 paired) + multi-agent (EXP-4)
  Table 5: Composition boundary (EXP-6) + attribution audit + EXP-7 + ASV/MR

Outputs: printed markdown + output/tables.csv (long format).
Judge-dependent columns show 'n/a' until run_judge.py has run.

Usage:
  python3 tables.py
  python3 tables.py --csv-only
"""

import argparse
import csv
import glob
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib import config  # noqa: E402
from lib.report import wilson_ci, rule_of_three  # noqa: E402

BASELINE_LABELS = {
    "gemini-3.1-flash-lite": config.OUTPUT_DIR / "gemini_labels.csv",
    "glm-4.5-air": config.OUTPUT_DIR / "glm_labels.csv",
}


def load_batches() -> list:
    rows = []
    for f in sorted(glob.glob(str(config.OUTPUT_DIR / "exp*_batch_*.csv"))):
        with open(f, newline="", encoding="utf-8", errors="replace") as fh:
            rows.extend([r for r in csv.DictReader(fh)])
    return rows


def load_judged() -> dict:
    judged = {}
    f = config.OUTPUT_DIR / "judged.csv"
    if not f.exists():
        return judged
    with open(f, newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            judged[(r["session_id"], int(r["turn"]))] = r
    return judged


def adoption_rate(rows, judged, exp: str = None, cell: str = None,
                  mech: str = None) -> dict:
    """Per-session adoption (any judged turn >= 5 with t1=1)."""
    by = defaultdict(lambda: {"n": 0, "adopt": 0})
    sessions = defaultdict(dict)
    for r in rows:
        if exp and r["exp"] != exp:
            continue
        if cell and r["cell"] != cell:
            continue
        if mech and r["mechanism"] != mech:
            continue
        sessions[r["session_id"]].setdefault("meta", r)
        sessions[r["session_id"]][int(r["turn"])] = r
    for sid, s in sessions.items():
        meta = s.pop("meta")
        key = (meta.get("cell"), meta.get("model"), meta.get("mechanism"),
               meta.get("protocol"))
        hits = [judged[(sid, t)] for t in sorted(s) if (sid, t) in judged
                and t >= 5]
        if not hits:
            continue
        by[key]["n"] += 1
        if any(h["t1_adoption"] == "1" for h in hits):
            by[key]["adopt"] += 1
    return by


PROTO_LETTER = {"protocol_a_factual_inversion": "A", "protocol_b_synthetic_turn_injection": "B",
                "protocol_c_intent_subversion": "C", "protocol_d_reasoning_chain_corruption": "D",
                "protocol_e_confidence_miscalibration": "E"}


def baseline_adoption(model: str) -> dict:
    """the reference pipeline judged baseline: adoption per protocol (t1=1 at turn>=5)."""
    path = BASELINE_LABELS.get(model)
    if not path or not path.exists():
        return {}
    out = defaultdict(lambda: {"n": 0, "adopt": 0})
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            if r.get("turn") and int(r["turn"]) < 5:
                continue
            proto = PROTO_LETTER.get(r.get("protocol", ""), r.get("protocol", ""))
            if r.get("track1") == "1":
                out[proto]["adopt"] += 1
            out[proto]["n"] += 1
    return out


def fmt_pct(k, n):
    if n == 0:
        return "n/a"
    lo, hi = wilson_ci(k, n)
    return f"{100.0*k/n:.1f}% [{lo:.2f},{hi:.2f}]"


def table1(rows):
    print("\n## Table 1 - Detection / FP audit (judge-free)")
    for cell in ["1a", "1b", "sentinel", "1d"]:
        sub = [r for r in rows if r["cell"] == cell]
        if not sub:
            continue
        for (model, proto, cond), grp in _group(sub, ["model", "protocol", "condition"]).items():
            if cell == "1b":
                flags = sum(int(r["flagged"]) for r in grp)
                print(f"  {cell:8s} {model:24s} {proto} {cond:14s}: "
                      f"{flags} flags / {len(grp)} rows (rule-of-three "
                      f"{rule_of_three(len(grp))*100:.1f}%)")
            else:
                inj = [r for r in grp if int(r["turn"]) == 5]
                k = sum(int(r["flagged"]) for r in inj)
                n = len(inj)
                print(f"  {cell:8s} {model:24s} {proto} {cond:14s}: "
                      f"{k}/{n} = {fmt_pct(k, n)}")


def _group(rows, keys):
    out = defaultdict(list)
    for r in rows:
        out[tuple(r.get(k, "") for k in keys)].append(r)
    return out


def table2(rows, judged):
    print("\n## Table 2 - Adoption reduction (EXP-1c, defended vs baseline)")
    by = adoption_rate(rows, judged, exp="EXP-1", cell="1c")
    for (cell, model, mech, proto), v in sorted(by.items()):
        base = baseline_adoption(model)
        b = base.get(proto, {"n": 0, "adopt": 0})
        print(f"  {model:24s} {proto}: defended {v['adopt']}/{v['n']} "
              f"({fmt_pct(v['adopt'], v['n'])})  baseline {fmt_pct(b['adopt'], b['n'])}")
    if not by:
        print("  (run run_judge.py first - adoption pending)")


def table3(rows, judged):
    print("\n## Table 3 - Comparative harness ranking (EXP-5)")
    print("  mech proto model | detection | clean-FP | adoption | med-lat(ms)")
    sub = [r for r in rows if r["exp"] == "EXP-5"]
    clean = [r for r in sub if r["cell"] == "clean_subset"]
    for (mech, proto, model), grp in sorted(_group(
            [r for r in sub if r["cell"].startswith("main_")],
            ["mechanism", "protocol", "model"]).items()):
        inj = [r for r in grp if int(r["turn"]) == 5]
        k = sum(int(r["flagged"]) for r in inj)
        n = len(inj)
        cfp = [r for r in clean if r["mechanism"] == mech and r["model"] == model]
        cfp_f = sum(int(r["flagged"]) for r in cfp)
        lat = statistics.median([float(r["latency_ms"]) for r in grp])
        adopt = adoption_rate(sub, judged, cell=f"main_{proto}", mech=mech)
        ad = adopt.get((f"main_{proto}", model, mech, proto))
        ad_str = f"{ad['adopt']}/{ad['n']}" if ad else "n/a"
        print(f"  {mech}  {proto}  {model:24s} | {fmt_pct(k, n):>12s} | "
              f"{cfp_f}/{len(cfp)} | {ad_str:>8s} | {lat:.0f}")


def table4(rows, judged):
    print("\n## Table 4 - Overhead (EXP-3 paired) + multi-agent (EXP-4)")
    off = [r for r in rows if r["exp"] == "EXP-3"]
    on = [r for r in rows if r["exp"] == "EXP-1" and r["cell"] == "1c"]
    on_lat = {r["session_id"]: float(r["latency_ms"]) for r in on}
    pairs = defaultdict(lambda: {"on": [], "off": []})
    for r in off:
        pairs[r["pair_id"]]["off"].append(float(r["latency_ms"]))
    for pid, v in pairs.items():
        v["on"] = [on_lat.get(pid, 0.0)] * len(v["off"])
    if pairs:
        for pid, v in pairs.items():
            delta = [(o - n) / n * 100 for n, o in zip(v["on"], v["off"]) if n > 0]
            if delta:
                print(f"  pair {pid}: median delta {statistics.median(delta):.2f}% "
                      f"(P95 {sorted(delta)[int(0.95*len(delta))-1]:.2f}%)")
        print("  NOTE: stack compute is microseconds (local hashing); the delta is "
              "network-variance-dominated. Gate (<5%) assessed on the distribution, "
              "reported with the variance caveat, not as a precise overhead estimate.")
    else:
        print("  (EXP-3 pairs pending)")
    for cond in ["clean", "midtransfer", "store"]:
        sub = [r for r in rows if r["exp"] == "EXP-4" and r["cell"] == cond]
        post = [r for r in sub if int(r["turn"]) >= 8]
        det = len(set(r["session_id"] for r in post if int(r["flagged"])))
        ns = len(set(r["session_id"] for r in sub))
        print(f"  EXP-4 {cond:12s}: {det}/{ns} sessions flagged post-handoff")


def table5(rows, judged):
    print("\n## Table 5 - Composition (EXP-6) + attribution + EXP-7")
    for cond in ["salami", "farma"]:
        sub = [r for r in rows if r["exp"] == "EXP-6" and r["cell"] == cond]
        ns = len(set(r["session_id"] for r in sub))
        flags = sum(int(r["flagged"]) for r in sub)
        adopt = adoption_rate(sub, judged, cell=cond)
        ev = sum(v["adopt"] for v in adopt.values())
        print(f"  EXP-6 {cond:8s}: {flags} tier flags / {ns} sessions; "
              f"evasion-as-adoption {ev}/{ns} (judge: {'yes' if adopt else 'pending'})")
    attr = Counter()
    for r in rows:
        bl = r.get("blocking_layer", "")
        if bl:
            attr[bl] += 1
    print(f"  Attribution (blocking_layer): {dict(attr) if attr else 'no flags yet'}")
    for tag in ["exp7a", "exp7b"]:
        sub = [r for r in rows if r["session_id"].startswith(tag)]
        if not sub:
            continue
        flags = sum(1 for r in sub if int(r["flagged"]))
        print(f"  {tag}: {flags} mechanism flags / {len(set(r['session_id'] for r in sub))} sessions "
              f"(ASR vs published range at analysis time)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-only", action="store_true")
    args = parser.parse_args()

    rows = load_batches()
    judged = load_judged()
    print(f"Batches: {len(rows)} rows; judged rows: {len(judged)}")

    if not args.csv_only:
        table1(rows)
        table2(rows, judged)
        table3(rows, judged)
        table4(rows, judged)
        table5(rows, judged)

    out = config.OUTPUT_DIR / "tables.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["table", "cell", "key", "metric", "value"])
        for r in rows:
            w.writerow(["raw", r["cell"], r["session_id"], "flagged", r["flagged"]])
    print(f"\nSaved raw export: {out} (paper-ready tables assembled in the "
          f"manuscript from the printed sections)")


if __name__ == "__main__":
    main()
