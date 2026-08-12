"""lib.report - Wilson CIs, rule-of-three, and per-cell summaries.

All proportions reported with Wilson 95% confidence intervals
(pre_registration.md section 5). Zero-observed cells report the
rule-of-three upper bound 3/n.
"""

import math
from collections import defaultdict


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple:
    """95% Wilson interval for k/n. Returns (lower, upper)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def wilson_lb_at_100(n: int, z: float = 1.96) -> float:
    """Lower bound for k=n (closed form n/(n+z^2))."""
    return n / (n + z * z)


def rule_of_three(n: int) -> float:
    """95% upper bound on a proportion with 0 observed in n trials."""
    return 3.0 / n if n > 0 else 1.0


def detection_summary(rows, injection_turn: int = 5) -> dict:
    """Per-cell detection: flags at the injection turn."""
    by_key = defaultdict(lambda: {"injected": 0, "flagged": 0, "total_rows": 0})
    for r in rows:
        key = (r.get("cell"), r.get("protocol"), r.get("model"),
               r.get("mechanism"))
        by_key[key]["total_rows"] += 1
        if int(r.get("turn") or 0) == injection_turn:
            by_key[key]["injected"] += 1
            by_key[key]["flagged"] += int(r.get("flagged") or 0)
    out = {}
    for key, d in by_key.items():
        k, n = d["flagged"], d["injected"]
        lo, hi = wilson_ci(k, n)
        out[key] = {
            "detected": k, "n": n,
            "rate": 100.0 * k / n if n else 0.0,
            "wilson_lo": lo, "wilson_hi": hi,
        }
    return out


def fp_summary(rows, injection_turn: int = 5) -> dict:
    """Per-cell false positives: flags on turns that must be clean."""
    by_key = defaultdict(lambda: {"rows": 0, "flags": 0})
    for r in rows:
        key = (r.get("cell"), r.get("protocol"), r.get("model"),
               r.get("mechanism"))
        by_key[key]["rows"] += 1
        by_key[key]["flags"] += int(r.get("flagged") or 0)
    out = {}
    for key, d in by_key.items():
        n = d["rows"]
        out[key] = {
            "flags": d["flags"], "rows": n,
            "rule_of_three": rule_of_three(n) if d["flags"] == 0 else None,
        }
    return out


def print_detection(rows, title: str, injection_turn: int = 5) -> None:
    print(f"\n--- {title} ---")
    for key, s in sorted(detection_summary(rows, injection_turn).items()):
        print(f"  {key[0]:<14} {key[1]} {key[2]:<24} {key[3]}: "
              f"{s['detected']}/{s['n']} = {s['rate']:.1f}%  "
              f"Wilson 95% [{s['wilson_lo']:.3f}, {s['wilson_hi']:.3f}]")


def print_fp(rows, title: str) -> None:
    print(f"\n--- {title} ---")
    for key, s in sorted(fp_summary(rows).items()):
        r3 = f"rule-of-three {s['rule_of_three']*100:.1f}%" if s["rule_of_three"] is not None else ""
        print(f"  {key[0]:<14} {key[1]} {key[2]:<24} {key[3]}: "
              f"{s['flags']} flags / {s['rows']} rows  {r3}")
