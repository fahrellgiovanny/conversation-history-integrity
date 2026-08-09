"""Compute Cohen's Kappa: DeepSeek v4-pro vs gold standard pre-labels (120 turns)."""

import json, csv, time, sys
from pathlib import Path
from collections import Counter

csv.field_size_limit(sys.maxsize)

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from judge import call_judge

GOLD_PATH = SCRIPT_DIR / "gold_standard.jsonl"
SIM_DIR = SCRIPT_DIR.parent / "simulation" / "output"

MODEL_MAP = {"GPT-5.4 Mini": "gpt", "Gemini-3.1 Flash-Lite": "gemini", "GLM-4.5-Air": "glm"}

gold = [json.loads(l) for l in open(GOLD_PATH)]

print("Building data index...", flush=True)
lookup = {}
for prefix in MODEL_MAP.values():
    for f in sorted(SIM_DIR.glob(f"{prefix}_batch_*.csv")):
        with open(f) as fh:
            for row in csv.DictReader(fh):
                key = (row["caseId"], row["protocol"], str(row["run"]), str(row["turn"]), prefix)
                lookup[key] = (row["prompt"], row["rawOutput"])
print(f"  {len(lookup)} turns indexed\n", flush=True)

pairs = []
t0 = time.time()

for i, g in enumerate(gold):
    prefix = MODEL_MAP.get(g["model"], "gpt")
    key = (g["caseId"], g["protocol"], str(g["run"]), str(g["turn"]), prefix)

    if key not in lookup:
        print(f"[{i+1:>3}/120] NOT FOUND", flush=True)
        continue

    prompt, output = lookup[key]
    t1, t2, just = call_judge(g["caseId"], prompt, output)

    if t1 is not None and t2 is not None:
        pairs.append((t1, g["prelabel_track1"], t2, g["prelabel_track2"]))

    m = "OK" if t1 == g["prelabel_track1"] and t2 == g["prelabel_track2"] else "DIFF"
    ela = time.time() - t0
    eta = ela / (i + 1) * 120 if (i + 1) > 0 else 0
    print(f"[{i+1:>3}/120] {m} {g['caseId']:<16} t{g['turn']:>2} DS=({t1},{t2}) pre=({g['prelabel_track1']},{g['prelabel_track2']}) [{ela:.0f}s]", flush=True)

# Kappa
n = len(pairs)
if n == 0:
    print("No valid pairs")
    sys.exit(1)

po_t1 = sum(1 for d, p, _, _ in pairs if d == p) / n
po_t2 = sum(1 for _, _, d, p in pairs if d == p) / n

jc1 = Counter(d for d, _, _, _ in pairs)
gc1 = Counter(p for _, p, _, _ in pairs)
pe_t1 = sum(jc1[k] * gc1[k] for k in jc1) / (n * n)
kappa_t1 = (po_t1 - pe_t1) / (1 - pe_t1) if pe_t1 < 1 else 1.0

jc2 = Counter(d for _, _, d, _ in pairs)
gc2 = Counter(p for _, _, _, p in pairs)
pe_t2 = sum(jc2[k] * gc2[k] for k in jc2) / (n * n)
kappa_t2 = (po_t2 - pe_t2) / (1 - pe_t2) if pe_t2 < 1 else 1.0

avg = (kappa_t1 + kappa_t2) / 2

print(f"\n=== COHEN'S KAPPA (DeepSeek v4-pro vs Gold Standard) ===")
print(f"Pairs: {n}")
print(f"T1 agreement: {po_t1:.1%}  Kappa: {kappa_t1:.3f}")
print(f"T2 agreement: {po_t2:.1%}  Kappa: {kappa_t2:.3f}")
print(f"Mean Kappa: {avg:.3f}")
print(f"{'PASS (almost perfect, κ ≥ 0.81 per Landis & Koch 1977)' if avg >= 0.81 else 'SUBSTANTIAL (0.61–0.80)'}")
