# RUNBOOK - Full Reproduction

Step-by-step reproduction of the evaluation described in the paper. All
commands run from this directory. The runners are resume-safe: interrupted
batches continue from the last completed session.

## 1. Environment

- Python 3.9+
- Dependencies: `openai`, `google-genai`, `openpyxl`

```
pip install openai google-genai openpyxl
```

## 2. API keys

Set as environment variables before running:

```
export GEMINI_API_KEY=...
export ZHIPUAI_API_KEY=...
export OPENAI_API_KEY=...
export DEEPSEEK_API_KEY=...
```

Key roles: Gemini and GLM are the evaluated models; GPT is the model with
zero baseline adoption and the cross-family judge; DeepSeek is the primary judge.

## 3. Run the experiments

Run in order. Each writes `output/<tag>_batch_*.csv`.

```
python3 simulation/run_exp1.py     # L1 scale evaluation (1,212 sessions)
python3 simulation/run_exp2.py     # L2/L3 tiers (300 sessions)
python3 simulation/run_exp3.py     # paired overhead sub-study (30 sessions)
python3 simulation/run_exp4.py     # multi-agent memory (60 sessions)
python3 simulation/run_exp5.py     # comparative harness, M1-M7 (920 sessions)
python3 simulation/run_exp6.py     # composition boundary + fragment-size sweep (120)
python3 simulation/run_exp7.py     # external anchors: AgentDojo, lifecycle, PoisonedRAG (187)
python3 simulation/run_exp8.py     # instruction-override gate family (300)
python3 simulation/run_exp8_probe.py   # shape boundary (60, exploratory)
python3 simulation/run_t3v2.py     # guard-model variant (60)
```

Total: 3,249 sessions. Some runners accept `--model gemini|glm`,
`--mech`, `--cell`, or `--condition` to restrict a batch.

## 4. Judge pass

Scores adoption (track 1) and collapse severity (track 2) on the
adoption-relevant turns with the primary judge (DeepSeek flash family):

```
python3 validator/run_judge.py
python3 validator/rebuild_judged_union.py
python3 validator/merge_judged.py
```

`rebuild_judged_union.py` merges a re-judged partial pass with the existing
full snapshot (`output/judged_full_backup.csv`), if any; `merge_judged.py`
writes the labels back into the batch files. The judge rubric and
prompts are in `lib/judge.py`.

## 5. Judge validation

- Verdict-mode sensitivity (strict / lenient / "I don't know"):
  `python3 validator/mode_judge.py`
- Cross-family agreement (GPT judge on a 300-row sample):
  `python3 validator/cross_judge.py`
- Flash-vs-pro agreement on a sample:
  `python3 validator/compare_judge_models.py`
- Human-annotation workbook (440 stratified turns):
  `python3 validator/build_annotation_file.py`

## 6. Analysis

```
python3 validator/audit_results.py    # all headline proportions + Wilson 95% CIs
python3 validator/tables.py    # ASV/MR tables for the comparative ranking
```

## Notes

- Session seeds derive from the explicit SHA-256 mapping
  `seed = SHA-256("case:protocol:run")[:8 bytes] mod 2^32` (lib/seeds.py); Python's
  built-in hash() is never used, being unstable across interpreters and platforms.
  Sessions are therefore deterministic given the model and the API response.
- Model and SDK versions are pinned in the run logs; API-version drift can
  change raw outputs, which is why outputs are not committed.
- The judge rubric and prompts ship with the release.
