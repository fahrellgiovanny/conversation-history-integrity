#!/usr/bin/env python3
"""build_agentdojo_manifest - extract official AgentDojo scenarios into the
Integrity Framework manifest (benchmarks/agentdojo_scenarios.json).

Source: official AgentDojo release (ethz-spylab/agentdojo, MIT license).
Texts are extracted VERBATIM from the official task definitions; only the
DELIVERY into the harness's session format is ours (documented below).

Rendering (documented in the paper):
  - content_injection: the user goal is the task; the attack's GOAL text is
    delivered as a tool-output content block at turn 2 (AgentDojo's native
    vector).
  - history_mutation: the SAME official texts, but the attack content is
    delivered as a retroactive modification of the stored history (the L1
    domain). This makes the "M1-M3 ASR <= 5% on mutation vectors" criterion
    testable on official texts; AgentDojo itself has no native
    history-mutation vectors.

Usage:
  python3 build_agentdojo_manifest.py <agentdojo_repo_path>
"""

import ast
import json
import sys
from pathlib import Path

REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else None
OUT = Path(__file__).resolve().parent / "agentdojo_scenarios.json"
SUITES = ["banking", "slack", "travel", "workspace"]


def eval_value(node, ns):
    """Evaluate an AST assignment node against the class namespace."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                expr = part.value
                if isinstance(expr, ast.Name):
                    out.append(str(ns.get(expr.id, "")))
                elif isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
                    out.append(str(ns.get(expr.attr, "")))
        return "".join(out)
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def extract_tasks(py_file):
    """Classes with PROMPT (user tasks) or GOAL (injection tasks)."""
    tasks, injections = [], []
    tree = ast.parse(py_file.read_text())
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        ns = {}
        for item in node.body:
            if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                v = eval_value(item.value, ns)
                if v is not None:
                    ns[item.targets[0].id] = v
        name = node.name
        prompt = ns.get("PROMPT")
        goal = ns.get("GOAL")
        if prompt and "InjectionTask" not in name:
            tasks.append({"id": name, "prompt": prompt})
        elif goal:
            injections.append({"id": name, "goal": goal})
    return tasks, injections


def main() -> None:
    if REPO is None or not REPO.exists():
        print("usage: build_agentdojo_manifest.py <agentdojo_repo_path>")
        sys.exit(1)

    scenarios = []
    for suite in SUITES:
        udir = REPO / "src" / "agentdojo" / "default_suites" / "v1" / suite
        user_file = udir / "user_tasks.py"
        inj_file = udir / "injection_tasks.py"
        if not user_file.exists():
            print(f"  SKIP {suite}: no user_tasks.py")
            continue
        tasks, injections = extract_tasks(user_file)
        _, inj2 = extract_tasks(inj_file) if inj_file.exists() else ([], [])
        injections += inj2
        if not tasks or not injections:
            print(f"  SKIP {suite}: tasks={len(tasks)} injections={len(injections)}")
            continue
        print(f"  {suite}: {len(tasks)} user tasks, {len(injections)} injections")
        task = tasks[0]
        # Canonical set first: 2 per suite (one per vector) -> first 8 cover
        # all 4 suites x both vectors; then injection-1 variants as extras.
        for inj in [injections[0]] + ([injections[1]] if len(injections) > 1 else []):
            for vector in ["content_injection", "history_mutation"]:
                scenarios.append({
                    "id": f"ad_{suite}_{task['id']}_{inj['id']}_{vector}",
                    "task": task["prompt"].strip(),
                    "vector": vector,
                    "turns": [
                        {"turn": 1, "content": task["prompt"].strip()},
                        {"turn": 2, "content": "Tool output received.",
                         "attack": {"content": inj["goal"].strip(), "kind":
                                    "mutation" if vector == "history_mutation" else "content"}},
                        {"turn": 3, "content": "Report what you did."},
                    ],
                    "target_action": inj["goal"].strip(),
                })

    import subprocess
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()[:12]

    # Interleave: first 8 = one per (suite, vector) -> all 4 suites x both
    # vectors; injection-1 variants follow.
    groups = [scenarios[i:i + 4] for i in range(0, len(scenarios), 4)]
    ordered = []
    for col in range(4):
        for g in groups:
            if col < len(g):
                ordered.append(g[col])
    scenarios = ordered
    manifest = {
        "source": "AgentDojo official release (ethz-spylab/agentdojo), MIT license",
        "repo_commit": commit,
        "citation": "Debenedetti et al., AgentDojo: A Dynamic Environment to Evaluate "
                    "Attacks and Defenses for LLM Agents, NeurIPS 2024 D&B, arXiv:2406.13352",
        "rendering_note": "Official texts verbatim; delivery rendered into the Integrity Framework "
                          "session format (content_injection = tool-output block; "
                          "history_mutation = retroactive history modification). "
                          "AgentDojo has no native history-mutation vectors; the "
                          "mutation rendering exists to make the M1-M3 mutation-vector "
                          "criterion testable on official texts.",
        "scenarios": scenarios,
    }
    OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(scenarios)} scenarios -> {OUT}")


if __name__ == "__main__":
    main()
