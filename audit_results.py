#!/usr/bin/env python3
"""audit_results.py - extract every headline number + Wilson CI from the
final conversation-history integrity data."""

import csv
import glob
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(2**31 - 1)
OUT = Path(__file__).resolve().parent / "output"


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def load(exp_prefix: str, **filters):
    rows = []
    for f in sorted(glob.glob(str(OUT / f"{exp_prefix}*_batch_*.csv"))):
        for r in csv.DictReader(open(f)):
            if all(r.get(k) == v for k, v in filters.items()):
                rows.append(r)
    return rows


def load_precise(exp: str, **filters):
    """Exact-tag load: only {exp}_batch_*.csv (so exp8 does not match
    exp8p/exp8g, and exp7 does not match exp7a/7b/7d)."""
    rows = []
    for f in sorted(glob.glob(str(OUT / f"{exp}_batch_*.csv"))):
        for r in csv.DictReader(open(f)):
            if all(r.get(k) == v for k, v in filters.items()):
                rows.append(r)
    return rows


def prop(rows, label, adopt_col="t1_adoption", turn_min=5):
    atk = [r for r in rows if int(r["turn"]) >= turn_min]
    n = len(atk)
    k = sum(1 for r in atk if r[adopt_col] == "1")
    p, lo, hi = wilson(k, n)
    print(f"{label}: {k}/{n} = {p*100:.1f}%  (Wilson 95% [{lo*100:.1f}, {hi*100:.1f}])")
    return p, lo, hi


def flagged_sessions(rows):
    """Session-level any-turn flag count: a session counts once if any of
    its turns carries a flag. This is the attribution basis of Table 5."""
    sess = {}
    for r in rows:
        sid = r["session_id"]
        sess.setdefault(sid, 0)
        if r["flagged"] == "1":
            sess[sid] = 1
    return sum(sess.values()), len(sess)


def main() -> None:
    print("=" * 70)
    print("FINAL RESULTS AUDIT (all cells, Wilson 95% CIs)")
    print("=" * 70)

    # --- EXP-1a/1b detection + FP (judge-free, batch flags) ---
    for model in ("gemini-3.1-flash-lite", "gpt-5.4-mini"):
        d = load("exp1", cell="1a", model=model)
        flagged = sum(1 for r in d if r["flagged"] == "1")
        n_sess = len(set(r["session_id"] for r in d))
        print(f"EXP-1a detection {model}: flags={flagged}/{n_sess} sessions "
              f"(pooled A+D, n=126, LB={wilson(126,126)[1]:.4f})")
    fp = load("exp1", cell="1b")
    n = len(set(r["session_id"] for r in fp))
    f = sum(1 for r in fp if r["flagged"] == "1")
    print(f"EXP-1b FP audit: {f} flags / {n} sessions (rule-of-three UB={3/n*100:.1f}%)")
    for cond in ("rehash", "content_routed"):
        d = load("exp1", cell="1d", condition=cond)
        k = sum(1 for r in d if r["flagged"] == "1")
        n_s = len(set(r["session_id"] for r in d))
        print(f"EXP-1d {cond}: flags={k}/{n_s}")

    # --- EXP-1c + 1c_neutral adoption ---
    for m in ("gemini-3.1-flash-lite", "glm-4.5-air"):
        for cell in ("1c", "1c_neutral"):
            rows = load("exp1", cell=cell, model=m)
            for p_ in ("A", "D"):
                sub = [r for r in rows if r["protocol"] == p_]
                fl = sum(1 for r in sub if r["flagged"] == "1")
                n_s = len(set(r["session_id"] for r in sub))
                prop(sub, f"EXP-1c({cell}) {m} {p_} (flags {fl}/{n_s})")

    # --- EXP-2 tiers ---
    for cell, lbl in [("l2a_forged", "L2a forged"), ("l2a_benign", "L2a benign"),
                      ("l2b_forged", "L2b forged"), ("l2b_benign", "L2b benign"),
                      ("l3_override", "L3 override"), ("l3_benign", "L3 benign")]:
        rows = load("exp2", cell=cell)
        fl = sum(1 for r in rows if r["flagged"] == "1")
        n_s = len(set(r["session_id"] for r in rows))
        print(f"EXP-2 {lbl}: flags={fl}/{n_s} sessions")

    # --- EXP-4 ---
    for cond in ("clean", "midtransfer", "store"):
        rows = load("exp4", cell=cond)
        fl = sum(1 for r in rows if r["flagged"] == "1")
        n_s = len(set(r["session_id"] for r in rows))
        print(f"EXP-4 {cond}: flags={fl}/{n_s}")

    # --- EXP-5: detection + adoption on A/C + clean subset ---
    r5 = load("exp5")
    for mech in ("M1", "M2", "M3", "M4", "M5", "M6", "M7"):
        for p_ in ("A", "C"):
            sub = [r for r in r5 if r["mechanism"] == mech and r["protocol"] == p_
                   and int(r["turn"]) == 5]
            fl = sum(1 for r in sub if r["flagged"] == "1")
            n_s = len(set(r["session_id"] for r in sub))
            p, lo, hi = wilson(fl, n_s)
            print(f"EXP-5 {mech} {p_} (turn 5): flags={fl}/{n_s} ({p*100:.0f}% [{lo*100:.0f},{hi*100:.0f}])")
    cl = [r for r in r5 if r["cell"] == "clean_subset"]
    for mech in ("M4", "M5", "M6", "M7"):
        sub = [r for r in cl if r["mechanism"] == mech]
        sess = {}
        for r in sub:
            sess.setdefault(r["session_id"], 0)
            if r["flagged"] == "1":
                sess[r["session_id"]] = 1
        n_s = len(sess)
        fl = sum(sess.values())
        print(f"EXP-5 clean subset {mech}: flagged sessions {fl}/{n_s} ({fl/max(n_s,1)*100:.0f}%)")
    for mech in ("M4", "M5", "M6", "M7"):
        sub = [r for r in cl if r["mechanism"] == mech]
        fl_t = sum(1 for r in sub if r["flagged"] == "1")
        n_t = len(sub)
        p, lo, hi = wilson(fl_t, n_t)
        print(f"EXP-5 clean subset {mech}: flagged turns {fl_t}/{n_t} ({p*100:.1f}% "
              f"[{lo*100:.1f}, {hi*100:.1f}])")

    # --- EXP-6 (both models) ---
    for model in ("gemini-3.1-flash-lite", "glm-4.5-air"):
        for cell in ("salami", "farma"):
            rows = load("exp6", cell=cell, model=model)
            fl = sum(1 for r in rows if r["flagged"] == "1")
            n_s = len(set(r["session_id"] for r in rows))
            prop(rows, f"EXP-6 {cell} {model} adoption (flags {fl}/{n_s})")

    # --- EXP-7 anchors (attack-turn ASR: turn 2 is the attack turn) ---
    for cell, mechs in [("agentdojo", ("control", "M1", "M2", "M3")),
                        ("memsecbench", ("control", "M1", "M3")),
                        ("poisonedrag", ("control", "M1", "M2", "M3", "STACK"))]:
        for mech in mechs:
            sub = [r for r in load("exp7", cell=cell, mechanism=mech)
                   if int(r["turn"]) == 2]
            prop(sub, f"EXP-7 {cell} {mech} (attack turn)", turn_min=1)

    # --- EXP-8 (both models) ---
    r8 = load("exp8")
    for model in ("gemini-3.1-flash-lite", "glm-4.5-air"):
        for cell in ("attack", "clean", "benign_directive"):
            for mech in ("M8a", "M8b", "M8c"):
                sub = [r for r in r8 if r["model"] == model and r["cell"] == cell
                       and r["mechanism"] == mech]
                fl = sum(1 for r in sub if r["flagged"] == "1")
                n_s = len(set(r["session_id"] for r in sub))
                ut = sum(float(r["utility_impact"] or 0) for r in sub)
                prop(sub, f"EXP-8 {model[:13]} {cell:16s} {mech} adoption "
                     f"(flags {fl}/{n_s} sess, util {ut:.0f})")

    # --- Probe ---
    rp = load("exp8p")
    for cond in ("control", "M8b", "M8c"):
        sub = [r for r in rp if r["condition"] == f"probe_{cond}"]
        prop(sub, f"PROBE {cond} escaped adoption")

    # --- Sentinel twins (EXP-1) ---
    st = load("exp1", cell="sentinel")
    fl, n_s = flagged_sessions(st)
    print(f"EXP-1 sentinel twins: {fl}/{n_s} sessions flagged "
          f"({sum(1 for r in st if r['flagged']=='1')} of {len(st)} turns)")

    # --- Table 5 backing: session-level attribution counts (any-turn) ---
    print()
    print("=== Table 5 backing (session-level, any-turn flag) ===")
    for cell, lbl in [("1a", "EXP-1a"), ("1c", "EXP-1c"), ("1c_neutral", "EXP-1c-neutral")]:
        fl, n_s = flagged_sessions(load("exp1", cell=cell))
        print(f"{lbl} ({cell}): {fl}/{n_s} sessions flagged")
    for cell, lbl in [("l2a_forged", "EXP-2 L2a"), ("l2b_forged", "EXP-2 L2b"), ("l3_override", "EXP-2 L3")]:
        fl, n_s = flagged_sessions(load("exp2", cell=cell))
        print(f"{lbl}: {fl}/{n_s} sessions flagged")
    for cond in ("midtransfer", "store"):
        fl, n_s = flagged_sessions(load("exp4", cell=cond))
        print(f"EXP-4 {cond}: {fl}/{n_s} sessions flagged")
    r5 = load("exp5")
    t1_s = t4_s = 0
    for mech in ("M1", "M2", "M3"):
        fl, n_s = flagged_sessions([r for r in r5 if r["mechanism"] == mech])
        print(f"EXP-5 {mech} (A, any turn): {fl}/{n_s} sessions flagged")
        t1_s += fl
    for mech in ("M4", "M5", "M6", "M7"):
        for cell, lbl in [("main_A", "A, any turn"), ("main_C", "C, any turn"), ("clean_subset", "clean subset")]:
            fl, n_s = flagged_sessions([r for r in r5 if r["mechanism"] == mech and r["cell"] == cell])
            print(f"EXP-5 {mech} {lbl}: {fl}/{n_s} sessions flagged")
        t4_s += 0  # accumulated after the loop below
    t4_s = sum(flagged_sessions([r for r in r5 if r["mechanism"] == mech])[0]
               for mech in ("M4", "M5", "M6", "M7"))
    print(f"EXP-5 TOTALS: T1 mechanisms {t1_s} sessions, M4-M7 semantic {t4_s} sessions, "
          f"all {t1_s + t4_s} sessions")
    for cell, mechs in [("agentdojo", ("M1", "M2", "M3")),
                        ("memsecbench", ("M1", "M3")),
                        ("poisonedrag", ("STACK",))]:
        for mech in mechs:
            fl, n_s = flagged_sessions(load("exp7", cell=cell, mechanism=mech))
            print(f"EXP-7 {cell} {mech}: {fl}/{n_s} sessions flagged")
    r8 = load_precise("exp8")  # exp8p/exp8g batches are separate cells
    tot8 = 0
    for cell in ("attack", "clean", "benign_directive"):
        fl, n_s = flagged_sessions([r for r in r8 if r["cell"] == cell])
        print(f"EXP-8 {cell}: {fl}/{n_s} sessions flagged")
        tot8 += fl
    print(f"EXP-8 TOTALS: {tot8} sessions flagged")
    for cell in ("attack", "clean", "benign_directive"):
        fl, n_s = flagged_sessions(load_precise("exp8g", cell=cell))
        print(f"T3-v2 {cell}: {fl}/{n_s} sessions escalated")

    # --- EXP-6 sweep (exploratory, Gemini only) ---
    for cell in ("salami_k3", "salami_k10"):
        rows = load("exp6", cell=cell)
        fl, n_s = flagged_sessions(rows)
        prop(rows, f"EXP-6 sweep {cell} adoption (flags {fl}/{n_s})")


if __name__ == "__main__":
    main()
