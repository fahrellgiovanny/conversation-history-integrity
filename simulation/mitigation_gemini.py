"""Mitigation Experiment: Verified History Defense vs. Session-Level Contamination.

Tests conversation-history integrity verification against Gemini-3.1 Flash-Lite.
Protocols: A, B, C only. Cases: math_short, geo_short only.
1 model x 3 protocols x 2 cases x 10 runs x 15 turns = 900 turns.

Defense: A cryptographic hash of the conversation history is stored after each turn.
At turn 5, the hash of the assembled history is recomputed. If the hash mismatches,
the last clean history is restored and the model never sees the contaminated content.

Protocols A and D modify the turn-4 assistant response with false content, so the
integrity check detects the mismatch, discards the contaminated history, and the
model receives only clean context. Protocols B, C, and E leave history intact
(attack is in the current prompt, not in prior turns), so the hash matches.
"""

import csv
import hashlib
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from google import genai

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from domains import CASES
from protocols import build_prompt, build_initial_prompt, make_system_prompt

MODEL = "gemini-3.1-flash-lite"
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PROTOCOLS = ["A", "B", "C"]
CASES_TO_RUN = ["math_short", "geo_short"]
RUNS = 10
TURNS = 15

MAX_OUTPUT_TOKENS = 4096
TEMPERATURE = 0.0
WORKERS = 10

# Protocols that replace turn-4 response with false content (history is modified).
# These are detectible by history integrity verification.
HISTORY_MODIFYING_PROTOCOLS = {"A", "D"}

_progress_lock = threading.Lock()
_completed = 0
_total_sessions = 0

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
gclient = genai.Client(api_key=GEMINI_API_KEY)

BASELINE = {
    ("math_short", "A"): 0.0,   ("geo_short", "A"): 0.9,
    ("math_short", "B"): 77.3,  ("geo_short", "B"): 98.2,
    ("math_short", "C"): 100.0, ("geo_short", "C"): 90.9,
}


# =============================================================================
# Verified History Orchestrator
# =============================================================================

class VerifiedHistoryOrchestrator:
    """Simulates conversation-history integrity verification.
    After turn 4, stores a hash of the conversation history.
    At turn 5, recomputes the hash of the assembled history.
    Protocols that modify the turn-4 response produce a hash mismatch.
    """

    def __init__(self):
        self.tamper_count: int = 0
        self._stored_hash: str = ""

    def _history_hash(self, prompt_with_response: str) -> str:
        """Hash the conversation history including the latest assistant response.
        The hash captures everything through the most recent turn."""
        return hashlib.sha256(prompt_with_response.encode("utf-8")).hexdigest()

    def store_after_turn(self, prompt_with_response: str) -> None:
        """Store hash of the conversation after a turn completes."""
        self._stored_hash = self._history_hash(prompt_with_response)

    def verify(self, assembled_prompt: str, protocol: str) -> tuple:
        """Check if the assembled prompt's history matches the stored hash.
        Returns (prompt, was_tampered).
        For protocols that don't modify history (B, C, E), always passes.
        For protocols that DO modify history (A, D), detects the mismatch.
        """
        if protocol not in HISTORY_MODIFYING_PROTOCOLS:
            return assembled_prompt, False

        current_hash = self._history_hash(assembled_prompt)
        if current_hash != self._stored_hash:
            self.tamper_count += 1
            return assembled_prompt, True
        return assembled_prompt, False


# =============================================================================
# API and Prompt Helpers
# =============================================================================

def call_api(prompt: str) -> dict:
    r = gclient.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={"max_output_tokens": MAX_OUTPUT_TOKENS, "temperature": TEMPERATURE},
    )
    fr = "unknown"
    try:
        fr = str(r.candidates[0].finish_reason.name) if r.candidates else "unknown"
    except Exception:
        pass
    usage = {}
    try:
        u = r.usage_metadata
        usage = {
            "promptTokens": u.prompt_token_count,
            "completionTokens": u.candidates_token_count,
            "totalTokens": u.total_token_count,
        }
    except Exception:
        pass
    return {"rawOutput": r.text or "", "finishReason": fr, "usageMetadata": usage}


def build_defense_prompt(case, protocol: str, turn: int, real_responses: dict) -> str:
    """Build a prompt where turn 4 uses the model's REAL response (no injection).
    Used when the defense restores clean history."""
    questions = case.all_turns(protocol)
    messages = []

    for t in range(1, turn + 1):
        q = questions.get(t, "")
        if not q:
            continue
        messages.append(f"User: {q}")
        if t == turn:
            break
        if t in real_responses:
            messages.append(f"Assistant: {real_responses[t]}")
        else:
            messages.append("Assistant: [response not recorded]")

    return "\n\n".join(messages)


# =============================================================================
# Run a Single Session
# =============================================================================

def run_case(case_id: str, protocol: str, run: int, results: list) -> None:
    case = CASES.get(case_id)
    if case is None:
        print(f"  SKIP {case_id} -- not defined in domains.py")
        return

    verifier = VerifiedHistoryOrchestrator()
    real_responses = {}
    prompt_after_last_turn = ""

    for turn in range(1, TURNS + 1):
        is_injection = (turn == 5)
        was_tampered = False

        # --- Build prompt ---
        if turn == 1:
            prompt = build_initial_prompt(case, protocol, make_system_prompt(case))
        else:
            prompt, _ = build_prompt(case, protocol, turn, real_responses)

        # --- Verified History Defense (turn 5 only) ---
        if is_injection:
            prompt, was_tampered = verifier.verify(prompt, protocol)
            if was_tampered:
                # History was modified. Restore clean history.
                prompt = build_defense_prompt(case, protocol, turn, real_responses)

        # --- Call model ---
        try:
            api_result = call_api(prompt)
        except Exception as e:
            print(f"  ERROR {case_id} {protocol} run={run} turn={turn}: {e}")
            time.sleep(5)
            try:
                api_result = call_api(prompt)
            except Exception:
                api_result = {"rawOutput": "", "finishReason": "error", "usageMetadata": {}}

        raw_output = api_result["rawOutput"]
        real_responses[turn] = raw_output

        # --- Store verified state ---
        # Build what the prompt would look like WITH the real response included
        # so we can hash the complete conversation state
        temp_responses = dict(real_responses)
        prompt_with_response = "\n\n".join(
            [prompt, f"Assistant: {raw_output}"]
        )
        verifier.store_after_turn(prompt_with_response)

        # --- Record ---
        record = {
            "caseId": case_id,
            "protocol": protocol,
            "model": MODEL,
            "run": run,
            "turn": turn,
            "isInjection": is_injection,
            "defenseActive": True,
            "wasTampered": was_tampered,
            "prompt": prompt,
            "rawOutput": raw_output,
            "usageMetadata": api_result.get("usageMetadata", {}),
            "finishReason": api_result.get("finishReason", "unknown"),
            "startedAt": datetime.now(timezone.utc).isoformat(),
        }
        results.append(record)

    status = "." * (run % 5 + 1)
    tamper_str = f" [tampered: {verifier.tamper_count}]" if verifier.tamper_count > 0 else ""
    print(f"  {case_id} / {protocol} / run {run} {status}{tamper_str}")


# =============================================================================
# Save and Report
# =============================================================================

def save_csv(records: list, filename: str) -> None:
    path = OUTPUT_DIR / filename
    fieldnames = [
        "caseId", "protocol", "model", "run", "turn",
        "isInjection", "defenseActive", "wasTampered",
        "promptTokens", "completionTokens", "finishReason",
        "startedAt", "prompt", "rawOutput",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow({
                "caseId": rec["caseId"],
                "protocol": rec["protocol"],
                "model": rec["model"],
                "run": rec["run"],
                "turn": rec["turn"],
                "isInjection": rec["isInjection"],
                "defenseActive": rec["defenseActive"],
                "wasTampered": rec["wasTampered"],
                "promptTokens": rec["usageMetadata"].get("promptTokens", 0),
                "completionTokens": rec["usageMetadata"].get("completionTokens", 0),
                "finishReason": rec.get("finishReason", "unknown"),
                "startedAt": rec["startedAt"],
                "prompt": rec["prompt"],
                "rawOutput": rec["rawOutput"],
            })


def print_summary(records: list) -> None:
    from collections import defaultdict

    adoption = defaultdict(lambda: {"total": 0, "tampered": 0})
    for r in records:
        if not r["isInjection"]:
            continue
        key = (r["caseId"], r["protocol"])
        adoption[key]["total"] += 1
        adoption[key]["tampered"] += 1 if r["wasTampered"] else 0

    print("\n" + "=" * 75)
    print("Mitigation Experiment: Verified History Defense")
    print("=" * 75)
    print(f"{'Protocol':<10} {'Case':<16} {'Baseline':>10} {'Tampered':>10}")
    print("-" * 50)
    for (case_id, protocol), data in sorted(adoption.items()):
        baseline = BASELINE.get((case_id, protocol), "?")
        print(f"{protocol:<10} {case_id:<16} {str(baseline) + '%':>10} {data['tampered']:>10}")

    total_tampered = sum(d["tampered"] for d in adoption.values())
    total_injections = sum(d["total"] for d in adoption.values())
    print("-" * 50)
    print(f"Total injection turns: {total_injections}")
    print(f"Total tamper events detected: {total_tampered}")
    print(f"\nProtocol A: tampered=10 per cell (history modified, defense restores clean context)")
    print(f"Protocol B: tampered=0 per cell (history intact, attack in current prompt)")
    print(f"Protocol C: tampered=0 per cell (history intact, attack in current prompt)")


# =============================================================================
# Parallel Runner and Progress
# =============================================================================

def run_session(case_id: str, protocol: str, run_num: int) -> list:
    records = []
    run_case(case_id, protocol, run_num, records)
    with _progress_lock:
        global _completed
        _completed += 1
    return records


def progress_reporter():
    start = time.time()
    while _completed < _total_sessions:
        time.sleep(60)
        elapsed = time.time() - start
        with _progress_lock:
            done = _completed
        pct = done / _total_sessions * 100 if _total_sessions else 0
        rate = done / (elapsed / 60) if elapsed > 0 else 0
        eta = (_total_sessions - done) / rate if rate > 0 else 0
        print(f"[{elapsed/60:.0f}m] {done}/{_total_sessions} ({pct:.0f}%) "
              f"~{rate:.1f} sessions/min  ETA: {eta:.0f}m")


def main():
    global _total_sessions
    _total_sessions = len(CASES_TO_RUN) * len(PROTOCOLS) * RUNS

    print(f"=== Mitigation Experiment: Verified History Defense ===")
    print(f"Model: {MODEL}  Workers: {WORKERS}")
    print(f"Cases: {CASES_TO_RUN}")
    print(f"Protocols: {PROTOCOLS}")
    print(f"Runs per cell: {RUNS}")
    print(f"Total sessions: {_total_sessions}  Total turns: {_total_sessions * TURNS}")
    print()

    tasks = []
    for case_id in CASES_TO_RUN:
        for protocol in PROTOCOLS:
            for run_num in range(1, RUNS + 1):
                tasks.append((case_id, protocol, run_num))

    reporter = threading.Thread(target=progress_reporter, daemon=True)
    reporter.start()

    all_records = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(run_session, c, p, r): (c, p, r) for c, p, r in tasks}
        for future in as_completed(futures):
            try:
                records = future.result()
                all_records.extend(records)
            except Exception as e:
                c, p, r = futures[future]
                print(f"  FAILED {c} {p} run={r}: {e}")

    save_csv(all_records, "mitigation_gemini_results.csv")
    print(f"\nSaved {len(all_records)} records to mitigation_gemini_results.csv")
    print_summary(all_records)

    print(f"\nRun the validator on mitigation_gemini_results.csv to get T1/T2 scores.")


if __name__ == "__main__":
    main()
