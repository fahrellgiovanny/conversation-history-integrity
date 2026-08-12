"""lib.seeds - explicit, reproducible seed derivation.

Python's built-in hash() is randomized per interpreter process (PYTHONHASHSEED)
and unstable across interpreter versions and platforms; it must never be used
in any seed that claims reproducibility. All seeds in this package are derived
with SHA-256, which is stable across interpreters, versions, and platforms.

The canonical mapping: seed = SHA-256("case:protocol:run")[:8 bytes] mod 2^32.
"""

import hashlib


def seed_from(spec: str) -> int:
    """Deterministic 32-bit seed from an arbitrary spec string.

    >>> seed_from("chemistry_long:A:001") == seed_from("chemistry_long:A:001")
    True
    """
    digest = hashlib.sha256(spec.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


def cell_seed(case: str, protocol: str, run: str) -> int:
    """Per-cell seed for the fixed (case, protocol, run) mapping documented in
    the pre-registration."""
    return seed_from(f"{case}:{protocol}:{run}")
