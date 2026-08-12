"""lib - shared library for the conversation-history integrity (EXP-1..EXP-7) runners.

Frozen plan numbers per pre_registration.md (rev. 4, 2026-08-07) and
the pre-registration (pre_registration.md, rev. 4). Do not edit cell counts here without an
amendment in pre_registration.md.
"""

from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent

MODEL_GEMINI = "gemini-3.1-flash-lite"
MODEL_GLM = "glm-4.5-air"
MODEL_GPT = "gpt-5.4-mini"

# EXP-8: instruction-override family M8.
EXP8 = {
    "models": [MODEL_GEMINI, MODEL_GLM],
    "attack_n": 30,
    "benign_n": 10,
}

TURNS = 15
INJECTION_TURN = 5
WORKERS = 5  # per model: 5 Gemini + 5 GPT + 5 GLM can run concurrently
# Zhipu GLM-4.5-Air concurrency limit: 5 concurrent requests (user-confirmed
# 2026-08-07). The global worker cap is also 5, so every LLM run uses at
# most 5 concurrent calls per provider. Enforced globally in
# lib.api.call_with_retry (GLM semaphore) + config.WORKERS.
GLM_MAX_CONCURRENCY = 5
MAX_OUTPUT_TOKENS = 4096
TEMPERATURE = 0.0

OUTPUT_DIR = SCRIPT_DIR / "output"
BENCH_DIR = SCRIPT_DIR / "benchmarks"

# Case distribution across the 10-domain suite.
CASES = [
    "math_short", "math_long", "physics_short", "physics_long",
    "history_short", "history_long", "chemistry_short", "chemistry_long",
    "geo_short", "geo_long",
]

# Experiments in sequential run order (run one by one, user-invoked).
RUN_ORDER = ["EXP-1", "EXP-2", "EXP-3", "EXP-4", "EXP-5", "EXP-6", "EXP-7"]

# ---------------------------------------------------------------------------
# Frozen cell counts (rev. 4). Case distribution helper below spreads a
# cell's total sessions across the 10 cases (remainder to the first cases,
# deterministically).
# ---------------------------------------------------------------------------

EXP1 = {
    # 1a/1b run on Gemini AND GPT (three-model determinism audit, ):
    # detection/FP are mechanism properties; a second API family makes the
    # model-independence claim empirical, not assumed. 1c keeps Gemini+GLM
    # only (adoption cells need nonzero baseline; GPT baseline is 0.0%).
    "1a": {"protocols": ["A", "D"], "models": [MODEL_GEMINI, MODEL_GPT], "n": 63},
    "1b": {"protocols": ["B", "C", "E"], "models": [MODEL_GEMINI, MODEL_GPT], "n": 100},
    "1c": {"protocols": ["A", "D"], "models": [MODEL_GEMINI, MODEL_GLM], "n": 50},
}

# Sentinel-randomization (ChannelGuard): benign twins interleaved into the
# detection audit; sentinel flags must be 0 (flags are attack-driven).
EXP1_SENTINEL_N = 10  # per L1 protocol, Gemini

# EXP-1d - adaptive attacker (Gemini, n=20 per condition). The attacker KNOWS
# the defense and targets it: (a) rehash: tamper + re-store the digest over
# the tampered state (authorized-write boundary, trusted base violation);
# (b) content_routed: deliver the mutation via the current prompt instead of
# history (layer-routing boundary). Expected detection ~0 in both - the
# theorem's scope made explicit, not a failure.
EXP1_ADAPTIVE = {"conditions": ["rehash", "content_routed"], "n": 20}

EXP2_CELLS = [
    # (cell, protocols, n PER PROTOCOL): l2 cells = 2 protocols x 30 = 60
    # sessions each; l3 cells = 1 protocol x 30. Total = 300 (plan rev. 4).
    ("l2a_forged",   ["B", "E"], 30),
    ("l2a_benign",   ["B", "E"], 30),
    ("l2b_forged",   ["B", "E"], 30),
    ("l2b_benign",   ["B", "E"], 30),
    ("l3_override",  ["C"], 30),
    ("l3_benign",    ["C"], 30),
]

EXP3_PAIRS_PER_MODEL = 15

EXP4 = {"conditions": ["clean", "midtransfer", "store"], "n": 20}

EXP5 = {
    "mechanisms": ["M1", "M2", "M3", "M4", "M5", "M6", "M7"],
    "protocols": ["A", "C"],
    "models": [MODEL_GEMINI, MODEL_GLM],
    "n": 30,
    "clean_subset": {  # M4-M7 clean-history FP cell (classic defenses are semantic)
        "mechanisms": ["M4", "M5", "M6", "M7"],
        "models": [MODEL_GEMINI, MODEL_GLM],
        "n": 10,
    },
}

EXP6 = {
    "conditions": ["salami", "farma", "salami_k3", "salami_k10"],
    "n": 20,
}

EXP7 = {
    "agentdojo_scenarios": 8,
    "agentdojo_conditions": ["control", "M1", "M2", "M3"],
    "lifecycle_modes": 7,
    "lifecycle_per_mode": 5,
    "lifecycle_conditions": ["control", "M1", "M3"],
    # EXP-7d PoisonedRAG (official artifacts, USENIX Security 2025): the
    # STACK condition demonstrates the layer taxonomy on official RAG
    # attacks (L1 silent on arriving content, L2 flags absent provenance).
    "poisonedrag": {
        "scenarios": 10,
        "conditions": ["control", "M1", "M2", "M3", "STACK"],
    },
}


def per_case_counts(total_n: int, n_cases: int = 10) -> dict:
    """Deterministic spread of a cell's n sessions across the case suite."""
    base, rem = divmod(total_n, n_cases)
    counts = {c: base for c in CASES[:n_cases]}
    for c in CASES[:rem]:
        counts[c] += 1
    return counts
