"""verify_stack.l1_hash - T1 hash-based history integrity tier (Integrity Framework).

Implements Lemma 1 (deterministic storage-layer detection):
- digest stored after every clean turn boundary
- recompute-before-inject; mismatch flags the turn
- restore-and-log semantics: last clean serialized state is retained
- event records follow the C6 attribution schema

Model-agnostic: reads serialized state only (Lemma 3).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict, Optional


class L1HashTier:
    """T1: hash-based history integrity with restore-and-log."""

    TIER = "L1"
    BLOCKING_LAYER = "l1_hash"

    def __init__(self, hash_fn=hashlib.sha256):
        self._hash_fn = hash_fn
        self._stored_digest: Optional[str] = None
        self._last_clean: Optional[str] = None
        self.tamper_count = 0
        self.event_log: list = []

    # -- state management --------------------------------------------------

    def _digest(self, serialized: str) -> str:
        return self._hash_fn(serialized.encode("utf-8")).hexdigest()

    def store_state(self, serialized: str) -> None:
        """Persist digest + snapshot of a clean turn boundary."""
        self._stored_digest = self._digest(serialized)
        self._last_clean = serialized

    def restore(self) -> Optional[str]:
        """Return the last clean serialized state (None if none stored)."""
        return self._last_clean

    # -- verification ------------------------------------------------------

    def verify(self, serialized: str, sentinel: bool = False) -> Dict:
        """Recompute digest of the history about to be injected and compare.

        Returns an event dict with the unified C6 schema:
        {flagged, tier, blocking_layer, sentinel, restored, ts, utility_impact}
        """
        flagged = False
        event = {
            "flagged": False,
            "tier": self.TIER,
            "blocking_layer": None,
            "sentinel": sentinel,
            "restored": False,
            "utility_impact": 0.0,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if self._stored_digest is None:
            # First turn: nothing stored yet, nothing to verify against.
            return event

        current = self._digest(serialized)
        if current != self._stored_digest:
            self.tamper_count += 1
            flagged = True
            event.update(
                {
                    "flagged": True,
                    "blocking_layer": self.BLOCKING_LAYER,
                    "restored": True,
                }
            )
            self.event_log.append(event)
        return event


def demo_self_check() -> None:
    """Local, API-free check of Lemma 1 behavior (detection + soundness)."""
    tier = L1HashTier()
    clean = "User: what is 1+1?\nAssistant: 2"
    tier.store_state(clean)

    # identical bytes -> no flag (soundness)
    assert tier.verify(clean)["flagged"] is False, "soundness violated"

    # any byte change -> flag (coverage)
    tampered = clean.replace("2", "1")
    ev = tier.verify(tampered)
    assert ev["flagged"] is True, "coverage violated"
    assert ev["blocking_layer"] == "l1_hash"
    assert ev["restored"] is True

    # restore returns the last clean state
    assert tier.restore() == clean

    print("L1HashTier self-check passed (Lemma 1: detection + soundness).")


if __name__ == "__main__":
    demo_self_check()
