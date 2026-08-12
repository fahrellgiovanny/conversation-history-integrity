#!/usr/bin/env python3
"""cross_judge.py - third-judge-family cross-check.

Re-judges a stratified ~300-row sample with GPT (gpt-5.4-mini, OpenAI) and
compares t1 against the deepseek-v4-flash labels. Judge-invariance across
families strengthens every behavioral claim in the paper.

Output: output/cross_judge.csv + agreement summary.
"""

import csv
import glob
import os
import random
import sys
from pathlib import Path

csv.field_size_limit(2**31 - 1)
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "simulation"))

from domains import CASES  # noqa: E402
import run_judge as J  # noqa: E402
from lib import config  # noqa: E402

TARGET = 300
SEED = 20260809
OUT = _ROOT / "output" / "cross_judge.csv"


def load_sessions() -> dict:
    sessions = {}
    for f in sorted(glob.glob(str(_ROOT / "output" / "exp*_batch_*.csv"))):
        for r in csv.DictReader(open(f)):
            sid = r.get("session_id", "")
            if sid:
                sessions.setdefault(sid, {})[int(r["turn"])] = r
    return sessions


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set")

    sessions = load_sessions()
    judged = list(csv.DictReader(open(_ROOT / "output" / "judged.csv")))

    # stratified sample: attack turns (>=5) only, up to 15 per (cell, model)
    rng = random.Random(SEED)
    pool = {}
    for r in judged:
        if int(r["turn"]) < 5:
            continue
        key = (r["cell"], r["model"])
        if r["session_id"] not in sessions:
            continue
        pool.setdefault(key, []).append(r)
    sampled = []
    for key, rows in pool.items():
        rng.shuffle(rows)
        sampled.extend(rows[:15])
    rng.shuffle(sampled)
    sampled = sampled[:TARGET]
    print(f"sample: {len(sampled)} rows across {len(set((r['cell']) for r in sampled))} cells")

    import judge as jm
    jm._client_kwargs = dict(api_key=os.environ["OPENAI_API_KEY"], max_retries=0)
    jm.MODEL = "gpt-5.4-mini"
    jm.JUDGE_NAME = "GPT-5.4-mini"

    agree = disagree = failed = 0
    rows = []
    for i, r in enumerate(sampled):
        sid, turn = r["session_id"], int(r["turn"])
        sess = sessions[sid]
        case = CASES.get(r["case"])
        context = J.rebuild_prompt(sess[turn], {t: sess[t].get("raw_output", "")
                                                for t in sess}, case) if case else ""
        try:
            t1, t2, just = jm.call_judge(r["case"], context,
                                         sess[turn].get("raw_output", ""),
                                         retries=0)
        except Exception as e:  # noqa: BLE001
            t1, t2, just = None, None, str(e)[:200]
        if t1 is None:
            failed += 1
            label = "FAIL"
        else:
            label = "agree" if str(t1) == str(r["t1_adoption"]) else "disagree"
            if label == "agree":
                agree += 1
            else:
                disagree += 1
        rows.append({"session_id": sid, "turn": turn, "cell": r["cell"],
                     "model": r["model"], "flash_t1": r["t1_adoption"],
                     "gpt_t1": "" if t1 is None else t1, "verdict": label})
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(sampled)}")
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    scored = agree + disagree
    print(f"AGREEMENT: {agree}/{scored} = {agree/scored*100:.1f}%  "
          f"disagreements {disagree}  failures {failed}")
    print(f"saved: {OUT}")


if __name__ == "__main__":
    main()
