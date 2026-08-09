# Simulation — Experiment runners, verification stack, and harness

This folder reproduces every experiment of the integrity-framework paper.
It mirrors the layout of the companion `epistemic-policy-divergence`
repository's `simulation/` folder: shared domain/protocol definitions plus
per-model runners, with results written as CSV batches.

## Structure

```
simulation/
├── run_exp1.py … run_exp7.py  # The seven experiments (resume-safe)
├── integritylib/                 # config, API clients, session runner, checkpointing
├── verify_stack/              # T1 hash, T2 provenance, T3 sanitizer, M1–M7 mechanisms
├── benchmarks/                # EXP-7 external anchor manifests (AgentDojo, MemSecBench, PoisonedRAG)
├── domains.py                 # 10 knowledge domains (math, physics, history, chemistry, geo)
├── protocols.py               # 5 contamination protocols (A–E)
├── mitigation_gemini.py       # Verified-history orchestration (shared with Paper 0)
├── plans/                     # Protocol/domain planning texts
└── pre_registration.md        # Frozen claims, gates, sample sizes (rev. 5)
```

## Running an experiment

```bash
# dry run first (no API calls)
python3 run_exp1.py --dry

# real run (resume-safe; re-invoking continues where it stopped)
python3 run_exp1.py
python3 run_exp1.py --workers 10
```

Output: `output/integrity/expN_batch_*.csv`, unified schema:
`session_id, exp, cell, model, protocol, case, mechanism, run, turn, flagged,
tier, blocking_layer, sentinel, restored, t1_adoption, t2_severity,
utility_impact, latency_ms, event_log, promptTokens, completionTokens`.

## The experiments

| Runner | Sessions | Cells | Gate |
|---|---|---|---|
| `run_exp1.py` | 1,112 | 1a detection (n=63), 1b clean-FP (n=100), 1c adoption (n=50), 1d adaptive, sentinel | Wilson LB ≥ 0.97; FP < 3% |
| `run_exp2.py` | 300 | L2a source authenticity, L2b role-tag integrity, L3 sanitizer (forged + benign, n=30) | detection ≥ 80%; FP ≤ 10% |
| `run_exp3.py` | 30 | Paired same-day stack-off vs stack-on (EXP-1c subsample) | median delta < 5% |
| `run_exp4.py` | 60 | Clean / mid-transfer / store tampering (n=20) | pooled Wilson LB ≥ 0.90 |
| `run_exp5.py` | 920 | M1–M7 × protocols A, C × Gemini, GLM (n=30) + clean-FP subset | ranked table, identical stress |
| `run_exp6.py` | 40 | Salami (MemCollusion-style), forged reasoning (FARMA-style) | evasion ≥ 50% |
| `run_exp7.py` | 140 | AgentDojo, MemSecBench, PoisonedRAG anchors | control ≈ published ballpark |

## Mechanism classes (EXP-5)

- M1 — hash-verify (T1 only)
- M2 — signed transitions (MutMem-style: Ed25519 + domain-separated commitments)
- M3 — digest + ledger, simulated trusted hardware (ElephantAgent-style)
- M4 — delimiter isolation, M5 — sandwich prevention,
  M6 — instructional prevention, M7 — known-answer detection
  (the four classic defenses of the formalization literature)


## Notes

- All runners are deterministic-tier auditable: detection/FP cells carry no
  model dimension (a hash either matches or it does not).
- Model availability contingency: if an API model is deprecated, re-measure
  the no-defense baseline on the successor model (temperature 0) before
  running defended cells, and report both generations (see
  `pre_registration.md` §8).
