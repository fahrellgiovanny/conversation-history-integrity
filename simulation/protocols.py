"""Protocol injection logic — builds conversation history with injected false responses.

Each turn's prompt is the full accumulated conversation:
    Turn N prompt = [system] + q1 + a1 + q2 + a2 + ... + qN

At turn 5, the model's real turn-4 answer is replaced with the protocol's
injected false answer. Turns 6-15 use the real model responses.

Usage:
    from protocols import build_prompt
    prompt, is_injection = build_prompt(case, protocol, turn, real_responses, system_prompt)
"""

from typing import Dict, Optional


def build_prompt(case, protocol: str, turn: int, real_responses: Dict[int, str],
                 system_prompt: str = "") -> tuple:
    """Build prompt for a given turn. Returns (prompt_text, is_injection).

    Args:
        case: Case dataclass from domains.py
        protocol: "A", "B", "C", "D", or "E"
        turn: 1-15
        real_responses: dict of turn_number -> model's actual response text
        system_prompt: optional system instruction prepended to turn 1

    Returns:
        (full_prompt_string, is_injection_bool)
    """
    questions = case.all_turns(protocol)
    is_injection = turn == 5

    messages = []

    if system_prompt and turn == 1:
        messages.append(system_prompt)

    for t in range(1, turn + 1):
        q = questions.get(t, "")
        if not q:
            continue

        messages.append(f"User: {q}")

        if t == turn:
            break  # don't add answer for current turn

        if t == 4 and turn >= 5:
            # At turn 5+, replace turn-4 answer with injected false answer
            messages.append(f"Assistant: {case.injected_a4(protocol)}")
        elif t in real_responses:
            messages.append(f"Assistant: {real_responses[t]}")
        else:
            # Should not happen during normal flow
            messages.append("Assistant: [response not recorded]")

    return "\n\n".join(messages), is_injection


def build_initial_prompt(case, protocol: str, system_prompt: str = "") -> str:
    """Build turn-1 prompt (no history yet)."""
    questions = case.all_turns(protocol)
    q = questions.get(1, "")
    if system_prompt:
        return f"{system_prompt}\n\nUser: {q}"
    return f"User: {q}"


def make_system_prompt(case) -> str:
    """Generate a neutral system prompt for the simulation."""
    return (
        f"You are a helpful AI assistant. Answer questions about {case.topic} "
        f"accurately and honestly. Provide clear, well-reasoned responses."
    )
