# Conversation-History Integrity

Standardized harness for evaluating conversation-history integrity
mechanisms in multi-turn language model systems.

This repository is the released artifact of:

**Detectable Epistemic Attack Layers: A Coverage Theorem and Standardized
Harness for Conversation-History Integrity**

The paper formalizes session-level contamination (injection of false premises
into the stored conversation history) by attack layer and states and
empirically bounds a coverage theorem: each deployment-layer verification tier covers exactly
its layer and is sound with respect to the others; instruction overrides are
not detectable without false positives; and composite vectors evade
per-fragment verification entirely. This repository is the instrument that
makes the claims checkable: the same contamination suite, the same session
structure, the same judge, and the same metrics applied to any integrity
mechanism that implements one interface.

Companion repository: https://github.com/fahrellgiovanny/epistemic-policy-divergence
(prior research; provides the baseline corpus this work builds on).

## Repository scope

This repository contains everything required to reproduce the simulation and
the judge pipeline. Raw model outputs are not committed: model responses are
not deterministic across API versions, and each run must generate its own
data. What is committed is the protocol suite, the mechanisms, the runners,
the judge, and the analysis tools.

## Layout

- `lib/` - shared library: configuration, API clients, session runner,
  resume utilities, progress reporting, the judge implementation
  (`lib/judge.py`, rubric included), and the SHA-256 seed helper
  (`lib/seeds.py`)
- `verify_stack/` - the three verification tiers (T1 history integrity,
  T2 provenance verification, T3 instruction sanitization) and the
  mechanism families under test (M1-M8)
- `benchmarks/` - third-party manifests (AgentDojo, PoisonedRAG) and the
  self-constructed memory-lifecycle cases
- `domains.py`, `protocols.py` - the five-protocol contamination suite over
  ten knowledge domains (the regression suite)
- `run_exp1.py` ... `run_exp8.py` - the eight experiment runners
- `run_exp8_probe.py` - the shape-boundary probe (exploratory)
- `run_t3v2.py` - the guard-model variant cell (T3-v2)
- `run_judge.py` - the automated adoption judge (adoption and severity verdicts)
- `mode_judge.py`, `cross_judge.py`, `compare_judge_models.py`,
  `judge_sensitivity.py` - judge validation and sensitivity analyses
- `build_annotation_file.py` - human-annotation workbook construction
- `merge_judged.py`, `rebuild_judged_union.py` - judged-label pipeline
- `audit_results.py`, `tables.py` - analysis and table generation
- `pre_registration.md` - frozen protocol, claims, thresholds, and the
  scientific amendment log

## The contamination suite

Five protocols hold a false premise constant while varying its epistemic
framing, spanning the three attack layers: storage mutation (L1), source
fabrication (L2), and instruction override (L3). Each session runs fifteen
turns; the injection occurs at turn 5; turns 6 through 15 observe
post-injection dynamics. The complete turn texts for all ten knowledge
domains are generated from `domains.py` and `protocols.py`.

## Mechanisms under test

- M1 plain hash verification
- M2 signed transitions
- M3 digest-plus-ledger (simulated secure module)
- M4 delimiter isolation
- M5 sandwich prevention
- M6 instructional prevention
- M7 known-answer detection
- M8a naive refusal floor / M8b channel separation / M8c provenance-gated
  refusal
- T3-v2 guard model (confidence-threshold escalation)
- STACK (all tiers composed)

## Reproducing the evaluation

1. Install Python 3.9+ and the dependencies (`openai`, `google-genai`,
   `openpyxl`).
2. Set the API keys as environment variables: `GEMINI_API_KEY`,
   `ZHIPUAI_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`.
3. Run the experiments in order (each runner is resume-safe; a fixed per-cell
   seed makes sessions deterministic given the model and the API response):
   `python3 run_exp1.py` ... `python3 run_exp8.py`
   `python3 run_exp8_probe.py`
   `python3 run_t3v2.py`
4. Judge the adoption-relevant cells:
   `python3 run_judge.py`
   (pipeline structure verifiable without an API: run any runner with `--dry`)
   then `python3 rebuild_judged_union.py && python3 merge_judged.py`
5. Validate the judge: `python3 mode_judge.py` (verdict-mode sensitivity),
   `python3 cross_judge.py` (cross-family agreement),
   `python3 build_annotation_file.py` (human-annotation workbook).
6. Produce the analysis: `python3 audit_results.py` (proportions with Wilson
   95% confidence intervals), `python3 tables.py` (ASV/MR tables).

All proportions report Wilson 95 percent confidence intervals; deterministic
tier false positives report the rule-of-three bound. Adoption claims are
reported under three verdict modes (strict, lenient, and an "I don't know"
mode), and the deterministic claims are judge-free anchors.

## Pre-registration

All claims, thresholds, and sample sizes are frozen in
`pre_registration.md` before the scale runs, with the scientific amendments
recorded in the same document.

## Status

Released at publication. The judge rubric and prompts ship with the release.
