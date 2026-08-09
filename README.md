# Conversation-History Integrity: Detectable Epistemic Attack Layers

A standardized harness for measuring conversation-history integrity mechanisms:
the attack-layer taxonomy, coverage theorem, seven-mechanism comparative
evaluation, and the contamination suite behind

> **Detectable Epistemic Attack Layers: A Coverage Theorem and Standardized
> Harness for Conversation-History Integrity** (Giovanny, Bayuningtyas,
> Mukharom, Firmansyah — under review)

Companion repository: [epistemic-policy-divergence](https://github.com/fahrellgiovanny/epistemic-policy-divergence)
(the session-level contamination benchmark whose baselines and dual-track
judge this project builds on).

## What this repository is

Conversational LLMs are stateless: application-layer software stores the
conversation history and reinjects it at every turn. That history is
infrastructure, and infrastructure can be modified. An adversary with write
access to the history store, a poisoned retrieval database, or a shared
multi-agent memory can rewrite what the model believes it previously said.

Contamination attacks differ not in what they say but in **where they land**:
stored history (L1), content channel (L2), or instruction channel (L3). This
repository ships:

1. **The verification stack** — a three-tier deployment-layer defense
   (hash-verify, provenance verification, instruction sanitization) with
   deterministic detection guarantees (see `simulation/verify_stack/`).
2. **The standardized harness** — seven mechanism classes (M1–M7) evaluated
   head-to-head under identical stress (identical protocols, models, judge,
   session structure) across seven experiments (EXP-1…EXP-7).
3. **The contamination suite** — the five-protocol, ten-domain corpus
   (A: factual inversion, B: synthetic turn injection, C: intent subversion,
   D: reasoning chain corruption, E: confidence miscalibration).
4. **The judge pipeline** — the dual-track automated judge (binary adoption +
   collapse severity), κ = 0.901-validated against a human gold standard.

## Repository layout

```
conversation-history-integrity/
├── simulation/          # Experiment runners, verification stack, harness
│   ├── run_exp1.py … run_exp7.py   # The seven experiments
│   ├── integritylib/       # Config, API clients, session runner, resume/checkpoint
│   ├── verify_stack/    # T1 hash, T2 provenance, T3 sanitizer, mechanisms M1–M7
│   ├── benchmarks/      # EXP-7 external anchor manifests (AgentDojo, MemSecBench)
│   ├── domains.py       # 10 knowledge domains
│   ├── protocols.py     # 5 contamination protocols
│   ├── plans/           # Protocol texts
│   └── pre_registration.md  # Frozen claims, gates, sample sizes
└── validator/           # Dual-track judge + validation tooling
    ├── judge.py         # DeepSeek dual-track judge (κ = 0.901)
    ├── run_judge.py  # Judge pass over simulation batches
    ├── kappa_check.py   # Inter-rater agreement
    ├── rules/rubric.json    # Published judge rubric
    └── gold_standard.jsonl  # Human gold standard corpus
```

## Quick start

### 1. Install dependencies

```bash
pip install openai google-genai
```

Requires Python 3.9+ (Node not required — this is a Python pipeline).

### 2. Set API keys

```bash
export GEMINI_API_KEY="..."   # simulation models (Gemini 3.1 Flash Lite)
export ZHIPUAI_API_KEY="..."  # GLM-4.5 Air (Zhipu open.bigmodel.cn)
export OPENAI_API_KEY="..."   # GPT-5.4 Mini (EXP-1 determinism audit)
export DEEPSEEK_API_KEY="..." # judge (validator/judge.py)
```

Keys are read from the environment only; nothing is stored in this repo.

### 3. Smoke test

```bash
cd simulation
python3 run_exp1.py --dry      # dry run: verifies pipeline, no API calls
cd ../validator
python3 run_judge.py --dry   # fake judge, pipeline validation
```

### 4. Run the experiments

```bash
cd simulation
python3 run_exp1.py   # L1 stack evaluation (~1,112 sessions)
python3 run_exp2.py   # L2/L3 semantic tiers (~300 sessions)
python3 run_exp3.py   # Paired overhead sub-study (~30 sessions)
python3 run_exp4.py   # Multi-agent memory (~60 sessions)
python3 run_exp5.py   # Comparative harness, M1–M7 (~920 sessions)
python3 run_exp6.py   # Composition boundary (~40 sessions)
python3 run_exp7.py   # External anchors (~140 sessions)
```

Every runner is **resume-safe**: completed sessions are checkpointed, and a
re-invocation only runs the missing cells. Rows are written to
`simulation/output/integrity/` as unified-schema batch CSVs.

### 5. Judge the sessions

```bash
cd validator
python3 run_judge.py            # scores all adoption-relevant cells
python3 run_judge.py --workers 10
```

The judge reads the batch CSVs, reconstructs the prompts the models saw
(temperature 0 makes reconstruction deterministic), and writes `judged.csv`
with per-turn adoption and severity verdicts. `kappa_check.py` reproduces
the inter-rater validation against `gold_standard.jsonl`.

## The seven experiments and their claims

| Experiment | Tests | Pre-registered gate |
|---|---|---|
| EXP-1 | L1 detection (100% atomic), clean-FP (0), adoption reduction | Wilson LB ≥ 0.97; FP < 3% |
| EXP-2 | L2a source authenticity, L2b role-tag integrity, L3 sanitizer | detection ≥ 80%; FP ≤ 10% |
| EXP-3 | Overhead vs deployed state-continuity systems | median paired delta < 5% |
| EXP-4 | Multi-agent memory transfer | pooled Wilson LB ≥ 0.90 |
| EXP-5 | Comparative harness, 7 mechanism classes | ranked table, identical stress |
| EXP-6 | Composition boundary (salami, forged reasoning) | tier-wise evasion ≥ 50% |
| EXP-7 | External anchors (AgentDojo, MemSecBench) | control reproduces published ballpark |

Gates, sample sizes, and statistical procedures are frozen in
`simulation/pre_registration.md`.


## Models

| Model | Provider | Role |
|---|---|---|
| Gemini 3.1 Flash Lite | Google | Primary vulnerable model + determinism audit |
| GLM-4.5 Air | Zhipu | Second vulnerable model |
| GPT-5.4 Mini | OpenAI | Determinism audit (zero baseline adoption) |
| DeepSeek V4 Pro | DeepSeek | Dual-track judge (κ = 0.901) |

## Claim discipline

Tamper-evidence proves **integrity**, never truth: a false premise can be
stored and signed correctly. This repository never claims "tamper-proof" or
"prevents contamination" — it detects and blocks at layer X, and the
boundaries (composition attacks, instruction overrides, adaptive attackers)
are documented in the paper and demonstrated in the experiments.

## License

MIT
