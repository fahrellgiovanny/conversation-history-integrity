"""integritylib.session - session runner implementing the paper's layer semantics.

Delivery semantics per SIMULATION_PAPER3 rev.4, section "session structure":
- L1 protocols (A, D): retroactive replacement of STORED history at turn 5.
  The mechanism checks the presented log against the stored digest, flags,
  and the harness restores the last clean state; the model only ever sees
  clean context (fail-closed).
- L2/L3 protocols (B, E, C): fabricated content or directive arrives in the
  CURRENT prompt (turn-5 question framing); the stored history is untouched,
  so L1 stays quiet (the false-positive control).
- Classic mechanisms (M4-M7, EXP-5) filter the assembled prompt instead of
  history: the attack presentation is the baseline prompt (with the turn-4
  substitution), and on detection the mechanism transforms the prompt.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from protocols import build_prompt, build_initial_prompt, make_system_prompt  # noqa: E402

SESSION_SCHEMA = [
    "session_id", "exp", "cell", "model", "protocol", "case", "mechanism",
    "condition", "run", "turn", "flagged", "tier", "blocking_layer",
    "sentinel", "restored", "t1_adoption", "t2_severity", "utility_impact",
    "latency_ms", "event_log", "raw_output", "promptTokens",
    "completionTokens", "finishReason", "startedAt", "pair_id",
]


def empty_row() -> Dict:
    return {k: "" for k in SESSION_SCHEMA}


def make_row(*, session_id: str, exp: str, cell: str, model: str, protocol: str,
             case_id: str, mechanism: str, condition: str, run: int, turn: int,
             ev: Dict, res: Dict, restored: int = 0, sentinel: int = 0,
             event_log: str = "", pair_id: str = "") -> Dict:
    """Unified row from an event dict + a model result dict."""
    row = empty_row()
    row.update({
        "session_id": session_id, "exp": exp, "cell": cell,
        "model": model, "protocol": protocol, "case": case_id,
        "mechanism": mechanism, "condition": condition,
        "run": run, "turn": turn,
        "flagged": int(ev.get("flagged", False)),
        "tier": ev.get("tier") or "",
        "blocking_layer": ev.get("blocking_layer") or "",
        "sentinel": sentinel,
        "restored": int(ev.get("restored", False)) or restored,
        "t1_adoption": "PILOT_NO_JUDGE",
        "t2_severity": "",
        "utility_impact": ev.get("utility_impact", 0.0),
        "latency_ms": round(float(res.get("latency_ms", 0.0) or 0.0), 2),
        "event_log": event_log,
        "raw_output": res.get("rawOutput", ""),
        "promptTokens": res.get("usageMetadata", {}).get("promptTokens", 0),
        "completionTokens": res.get("usageMetadata", {}).get("completionTokens", 0),
        "finishReason": res.get("finishReason", ""),
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "pair_id": pair_id,
    })
    return row


def clean_prompt(case, protocol: str, turn: int, real: Dict[int, str],
                 turn5_override: str = None) -> str:
    """Prompt from REAL responses only (no turn-4 substitution). The turn-5
    question carries the protocol's injection framing for L2/L3 protocols;
    for L1 protocols the framing references the (restored, clean) history.

    Turn 1 carries the same neutral system prompt as the baseline
    experiment, so defended sessions differ from baseline sessions ONLY by
    the defense (differential-protocol fidelity).
    """
    questions = dict(case.all_turns(protocol))
    if turn5_override:
        questions[5] = turn5_override
    msgs = []
    if turn == 1:
        msgs.append(make_system_prompt(case))
    for t in range(1, turn + 1):
        q = questions.get(t, "")
        if not q:
            continue
        msgs.append(f"User: {q}")
        if t == turn:
            break
        r = real.get(t)
        msgs.append(f"Assistant: {r if r is not None else '[response not recorded]'}")
    return "\n\n".join(msgs)


def baseline_prompt(case, protocol: str, turn: int, real: Dict[int, str]) -> str:
    """Baseline presentation (as the main experiment): turn-4 answer replaced
    by the protocol's injected false answer from turn 5 on. Turn 1 carries
    the neutral system prompt, exactly as the baseline experiment."""
    if turn == 1:
        return build_initial_prompt(case, protocol, make_system_prompt(case))
    return build_prompt(case, protocol, turn, real)[0]


def serialize_log(log: List[str]) -> str:
    return "\n\n".join(log)


def _injected_replacement(log: List[str], injected_text: str) -> List[str]:
    """Retroactive replacement of the last stored assistant response."""
    if not log:
        return log
    new_log = list(log)
    last = new_log[-1]
    if "Assistant: " in last:
        head, _ = last.rsplit("Assistant: ", 1)
        new_log[-1] = f"{head}Assistant: {injected_text}"
    else:
        new_log[-1] = last + f"\nAssistant: {injected_text}"
    return new_log


class SessionRunner:
    """Runs one 15-turn session and returns unified rows."""

    def __init__(self, mechanism, model_call: Callable[[str], dict],
                 dry: bool = False, sentinel: bool = False):
        self.mechanism = mechanism
        self.model_call = model_call
        self.dry = dry
        self.sentinel = sentinel

    def _call(self, prompt: str) -> Dict:
        t0 = time.perf_counter()
        res = self.model_call(prompt)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        res["latency_ms"] = latency_ms
        return res

    def run_history_session(self, case, protocol: str, *, session_id: str,
                            exp: str, cell: str, model: str, run: int,
                            attack: str = "mutation", mechanism_label: str = "M1",
                            condition: str = "", turn5_override: str = None,
                            tamper_text_fn: Callable[[object, str], str] = None,
                            pair_id: str = "") -> List[Dict]:
        """Standard 15-turn session.

        attack="mutation" (A/D): retroactive replacement of stored history
            at turn 5 (L1 protocols).
        attack="none" (B/C/E or clean cells): history untouched; the
            injection, if any, is delivered by the turn-5 question framing.
        """
        real: Dict[int, str] = {}
        log: List[str] = []
        rows: List[Dict] = []
        self.mechanism.begin_session()
        for turn in range(1, 16):
            if attack == "mutation" and turn == 5:
                presented = _injected_replacement(
                    log, tamper_text_fn(case, protocol) if tamper_text_fn
                    else case.injected_a4(protocol))
                ev = self.mechanism.check(serialize_log(presented))
            else:
                ev = self.mechanism.check(serialize_log(log))
            flagged = bool(ev.get("flagged"))

            prompt = clean_prompt(case, protocol, turn, real,
                                  turn5_override=turn5_override)
            res = self._call(prompt)
            serialized_turn = f"User: {prompt}\nAssistant: {res['rawOutput']}"
            real[turn] = res["rawOutput"]
            log.append(serialized_turn)
            # Restore-and-log semantics: continue on clean input and store
            # the new clean state at every turn boundary (flagged or not).
            self.mechanism.observe(serialize_log(log))

            row = empty_row()
            row.update({
                "session_id": session_id, "exp": exp, "cell": cell,
                "model": model, "protocol": protocol, "case": case.case_id,
                "mechanism": mechanism_label, "condition": condition,
                "run": run, "turn": turn,
                "flagged": int(flagged),
                "tier": ev.get("tier") or "",
                "blocking_layer": ev.get("blocking_layer") or "",
                "sentinel": int(self.sentinel),
                "restored": int(ev.get("restored", False)),
                "t1_adoption": "PILOT_NO_JUDGE",
                "t2_severity": "",
                "utility_impact": ev.get("utility_impact", 0.0),
                "latency_ms": round(res["latency_ms"], 2),
                "event_log": json.dumps(self.mechanism.event_log),
                "raw_output": res["rawOutput"],
                "promptTokens": res.get("usageMetadata", {}).get("promptTokens", 0),
                "completionTokens": res.get("usageMetadata", {}).get("completionTokens", 0),
                "finishReason": res.get("finishReason", ""),
                "startedAt": datetime.now(timezone.utc).isoformat(),
                "pair_id": pair_id,
            })
            rows.append(row)
        return rows

    def run_filter_session(self, case, protocol: str, *, session_id: str,
                           exp: str, cell: str, model: str, run: int,
                           mechanism_label: str, condition: str = "",
                           use_baseline_prompt: bool = False,
                           turn5_override: str = None) -> List[Dict]:
        """M4-M7 session: the mechanism filters the ASSEMBLED prompt."""
        real: Dict[int, str] = {}
        rows: List[Dict] = []
        self.mechanism.begin_session()
        for turn in range(1, 16):
            if use_baseline_prompt:
                prompt = baseline_prompt(case, protocol, turn, real)
            else:
                prompt = clean_prompt(case, protocol, turn, real,
                                      turn5_override=turn5_override)
            ev = self.mechanism.check(prompt)
            if ev.get("flagged") and ev.get("transformed_prompt"):
                prompt = ev["transformed_prompt"]
            res = self._call(prompt)
            real[turn] = res["rawOutput"]

            row = empty_row()
            row.update({
                "session_id": session_id, "exp": exp, "cell": cell,
                "model": model, "protocol": protocol, "case": case.case_id,
                "mechanism": mechanism_label, "condition": condition,
                "run": run, "turn": turn,
                "flagged": int(ev.get("flagged", False)),
                "tier": ev.get("tier") or "",
                "blocking_layer": ev.get("blocking_layer") or "",
                "sentinel": int(self.sentinel),
                "restored": 0,
                "t1_adoption": "PILOT_NO_JUDGE",
                "t2_severity": "",
                "utility_impact": ev.get("utility_impact", 0.0),
                "latency_ms": round(res["latency_ms"], 2),
                "event_log": json.dumps(self.mechanism.event_log),
                "raw_output": res["rawOutput"],
                "promptTokens": res.get("usageMetadata", {}).get("promptTokens", 0),
                "completionTokens": res.get("usageMetadata", {}).get("completionTokens", 0),
                "finishReason": res.get("finishReason", ""),
                "startedAt": datetime.now(timezone.utc).isoformat(),
                "pair_id": "",
            })
            rows.append(row)
        return rows
