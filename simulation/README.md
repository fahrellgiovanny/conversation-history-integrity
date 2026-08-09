# Simulation

This folder repeats every experiment of the integrity-framework paper. It uses the same layout as the `simulation/` folder of the companion repository `epistemic-policy-divergence`. It contains the shared domain and protocol definitions and the per-model runners. The runners write results as batch files in the comma-separated values (CSV) format.

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

## Run an experiment

```bash
# Do a dry run first. A dry run makes no API calls.
python3 run_exp1.py --dry

# Do a real run. Each runner is resume-safe.
# A new run continues where the previous run stopped.
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
| `run_exp1.py` | 1,112 | 1a detection (n=63), 1b clean false positives (n=100), 1c adoption (n=50), 1d adaptive, sentinel | Wilson lower bound at least 0.97; false positives below 3% |
| `run_exp2.py` | 300 | L2a source authenticity, L2b role-tag integrity, L3 sanitizer (forged + benign, n=30) | detection at least 80%; false positives at most 10% |
| `run_exp3.py` | 30 | Paired same-day stack-off vs stack-on (EXP-1c subsample) | median delta below 5% |
| `run_exp4.py` | 60 | Clean, mid-transfer, store tampering (n=20) | pooled Wilson lower bound at least 0.90 |
| `run_exp5.py` | 920 | M1–M7 × protocols A, C × Gemini, GLM (n=30) + clean false-positive subset | ranked table, identical stress |
| `run_exp6.py` | 40 | Salami (MemCollusion-style), forged reasoning (FARMA-style) | evasion at least 50% |
| `run_exp7.py` | 140 | AgentDojo, MemSecBench, PoisonedRAG anchors | control reproduces published ballpark |

## Mechanism classes (EXP-5)

- M1: hash verification. It uses T1 only.
- M2: signed transitions. It uses the MutMem style. It uses Ed25519 and domain-separated commitments.
- M3: digest and ledger. It uses the ElephantAgent style. The trusted hardware is simulated.
- M4: delimiter isolation.
- M5: sandwich prevention.
- M6: instructional prevention.
- M7: known-answer detection.
- M4 to M7 are the four classic defenses of the formalization literature.

## Notes

- The detection and false-positive cells carry no model dimension. A hash either matches or it does not.
- If an API model is no longer available, measure the no-defense baseline on the successor model first. Use temperature 0. Then run the defended cells. Report both model generations. See `pre_registration.md` for details.
