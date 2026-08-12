"""verify_stack.orchestrator - session orchestrator wrapping the T1 tier (conversation-history integrity).

Runs a 15-turn session with the verification stack active:
- store digest after every clean turn boundary
- verify the assembled history immediately before context assembly
- on flag: restore last clean state (restore-and-log), continue on clean input
- emits one session row per turn with the unified CSV schema

Interface matches Section 4.2 of the manuscript:
    verify(turn_context) -> (clean | tampered, restored_context, event_log)
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List


class SessionOrchestrator:
    """Drives one session; model_call(prompt) -> str is the only model touchpoint."""

    def __init__(self, model_call: Callable[[str], str], verify_stack: List):
        self.model_call = model_call
        self.tiers = verify_stack  # list of tiers with .verify/.store_state/.restore
        self.history: List[str] = []        # serialized turns (current)
        self._clean_history: List[str] = []  # snapshot of last clean state

    def _serialize(self) -> str:
        return "\n\n".join(self.history)

    def verify_context(self) -> Dict:
        """Run tiers over the assembled context; return the blocking event."""
        serialized = self._serialize()
        for tier in self.tiers:
            event = tier.verify(serialized)
            if event["flagged"]:
                return event
        return {"flagged": False, "tier": None, "blocking_layer": None}

    def run(self, turn_prompts: List[str], num_turns: int = 15,
            tamper_builder=None) -> List[Dict]:
        """Execute the session. turn_prompts[i] is the fully assembled prompt
        for turn i (injection already applied by the caller's protocol builder).
        tamper_builder(history) is applied to the STORED history immediately
        before the injection turn's verification (Protocol A/D semantics: the
        adversary modifies stored prior turns, not the current prompt).
        Returns per-turn rows."""
        rows = []
        for turn in range(1, num_turns + 1):
            prompt = turn_prompts[turn - 1] if turn <= len(turn_prompts) else ""

            if tamper_builder is not None and turn == 5:
                self.history = tamper_builder(list(self.history))

            event = self.verify_context()

            if event["flagged"]:
                # restore-and-log: revert to the last clean state and re-store
                # its digest so subsequent turns verify against the restored
                # state, not the tampered one
                self.history = list(self._clean_history)
                for tier in self.tiers:
                    if hasattr(tier, "store_state"):
                        tier.store_state(self._serialize())
                rows.append(self._row(turn, prompt, event, restored_from=True))
                continue

            t0 = time.perf_counter()
            raw = self.model_call(prompt)
            latency_ms = (time.perf_counter() - t0) * 1000.0

            self.history.append(f"User: {prompt}\nAssistant: {raw}")
            self._clean_history = list(self.history)
            for tier in self.tiers:
                if hasattr(tier, "store_state"):
                    tier.store_state(self._serialize())

            rows.append(self._row(turn, prompt, event, latency_ms=latency_ms))
        return rows

    def _row(self, turn: int, prompt: str, event: Dict,
             latency_ms: float = 0.0, restored_from=None) -> Dict:
        return {
            "turn": turn,
            "flagged": event["flagged"],
            "tier": event.get("tier"),
            "blocking_layer": event.get("blocking_layer"),
            "sentinel": event.get("sentinel", False),
            "restored": event["flagged"],
            "utility_impact": event.get("utility_impact", 0.0),
            "latency_ms": round(latency_ms, 2),
            "prompt": prompt,
            "restored_from": restored_from,
        }
