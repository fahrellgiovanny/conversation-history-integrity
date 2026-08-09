# Conversation-History Integrity: Detectable Epistemic Attack Layers

This repository measures conversation-history integrity mechanisms. It contains the attack-layer taxonomy, the coverage theorem, the seven-mechanism comparison, and the contamination suite.

> Paper: Detectable Epistemic Attack Layers: A Coverage Theorem and Standardized Harness for Conversation-History Integrity. Authors: Giovanny, Bayuningtyas, Mukharom, Firmansyah. The paper is under review.

Companion repository: [epistemic-policy-divergence](https://github.com/fahrellgiovanny/epistemic-policy-divergence). It contains the session-level contamination benchmark. This project uses its baselines and its dual-track judge.

## Purpose

A conversational Large Language Model (LLM) has no memory state of its own. Application software stores the conversation history. The software sends the history back to the model at every turn. An adversary can change this history. The adversary needs write access to the history store, to a retrieval database, or to a shared multi-agent memory.

Contamination attacks differ in where they land. There are three attack layers:

- L1: stored history.
- L2: content channel.
- L3: instruction channel.

This repository contains four parts:

1. The verification stack. It is a three-tier deployment-layer defense. It uses hash verification, provenance verification, and instruction sanitization. It gives deterministic detection guarantees. See `simulation/verify_stack/`.
2. The standardized harness. It compares seven mechanism classes (M1 to M7). All classes run under identical stress. The stress uses the same protocols, models, judge, and session structure. See EXP-1 to EXP-7.
3. The contamination suite. It is a five-protocol, ten-domain corpus. The protocols are A to E. They are factual inversion, synthetic turn injection, intent subversion, reasoning chain corruption, and confidence miscalibration.
4. The judge pipeline. It is a dual-track automated judge. Track 1 measures binary adoption. Track 2 measures collapse severity. The judge has agreement kappa = 0.901 with a human gold standard.

## Repository layout

```
conversation-history-integrity/
├── simulation/          # Experiment runners, verification stack, harness
│   ├── run_exp1.py … run_exp7.py   # The seven experiments
│   ├── integritylib/       # Config, API clients, session runner, checkpointing
│   ├── verify_stack/    # T1 hash, T2 provenance, T3 sanitizer, mechanisms M1–M7
│   ├── benchmarks/      # EXP-7 external anchor manifests (AgentDojo, MemSecBench)
│   ├── domains.py       # 10 knowledge domains
│   ├── protocols.py     # 5 contamination protocols
│   ├── plans/           # Protocol texts
│   └── pre_registration.md  # Frozen claims, gates, sample sizes
└── validator/           # Dual-track judge + validation tooling
    ├── judge.py         # DeepSeek dual-track judge (kappa = 0.901)
    ├── run_judge.py  # Judge pass over simulation batches
    ├── kappa_check.py   # Inter-rater agreement
    ├── rules/rubric.json    # Published judge rubric
    └── gold_standard.jsonl  # Human gold standard corpus
```

## Quick start

### 1. Install the dependencies

```bash
pip install openai google-genai
```

Use Python 3.9 or newer. Node is not required.

### 2. Set the API keys

```bash
export GEMINI_API_KEY="..."   # simulation models (Gemini 3.1 Flash Lite)
export ZHIPUAI_API_KEY="..."  # GLM-4.5 Air (Zhipu open.bigmodel.cn)
export OPENAI_API_KEY="..."   # GPT-5.4 Mini (EXP-1 determinism audit)
export DEEPSEEK_API_KEY="..." # judge (validator/judge.py)
```

API is the short form of Application Programming Interface. The runners read the keys from the environment. Nothing is stored in this repository.

### 3. Run a smoke test

```bash
cd simulation
python3 run_exp1.py --dry      # dry run: verifies pipeline, no API calls
cd ../validator
python3 run_judge.py --dry   # fake judge, pipeline validation
```

A dry run verifies the pipeline. It makes no API calls.

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

Each runner is resume-safe. It writes completed sessions to checkpoint files. A new run continues where the previous run stopped. The runners write rows to `simulation/output/integrity/` as batch files. The batch files use the comma-separated values (CSV) format.

### 5. Judge the sessions

```bash
cd validator
python3 run_judge.py            # scores all adoption-relevant cells
python3 run_judge.py --workers 10
```

The judge reads the batch files. It reconstructs the prompts that the models saw. Temperature 0 makes the reconstruction deterministic. The judge writes `judged.csv`. The file contains adoption and severity verdicts for each turn. Use `kappa_check.py` to repeat the inter-rater validation against `gold_standard.jsonl`.

## The seven experiments and their claims

| Experiment | Tests | Pre-registered gate |
|---|---|---|
| EXP-1 | L1 detection (100% atomic), clean false positives (0), adoption reduction | Wilson lower bound at least 0.97; false positives below 3% |
| EXP-2 | L2a source authenticity, L2b role-tag integrity, L3 sanitizer | detection at least 80%; false positives at most 10% |
| EXP-3 | Overhead vs deployed state-continuity systems | median paired delta below 5% |
| EXP-4 | Multi-agent memory transfer | pooled Wilson lower bound at least 0.90 |
| EXP-5 | Comparative harness, 7 mechanism classes | ranked table, identical stress |
| EXP-6 | Composition boundary (salami, forged reasoning) | tier-wise evasion at least 50% |
| EXP-7 | External anchors (AgentDojo, MemSecBench) | control reproduces published ballpark |

The gates, the sample sizes, and the statistical procedures are frozen in `simulation/pre_registration.md`.

## Models

| Model | Provider | Role |
|---|---|---|
| Gemini 3.1 Flash Lite | Google | Primary vulnerable model + determinism audit |
| GLM-4.5 Air | Zhipu | Second vulnerable model |
| GPT-5.4 Mini | OpenAI | Determinism audit (zero baseline adoption) |
| DeepSeek V4 Pro | DeepSeek | Dual-track judge (kappa = 0.901) |

## Claim discipline

Tamper evidence shows integrity. It does not show truth. A false premise can be stored and signed correctly. This repository does not claim "tamper-proof". It does not claim "prevents contamination". It detects attacks and blocks them at a specific layer. The boundaries are documented in the paper. They are shown in the experiments.

## License

MIT
