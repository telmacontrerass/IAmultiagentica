"""History trimming to stay within the model's context window."""

from __future__ import annotations

from typing import Any


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Quick estimate (~4 characters per token)."""
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += len(content)
        elif content is None and msg.get("tool_calls"):
            total += sum(
                len(str(tc.get("function", {})))
                for tc in msg["tool_calls"]
            )
        role = msg.get("role", "")
        total += len(role) + 8
    return max(1, total // 4)


def trim_messages(
    messages: list[dict[str, Any]],
    max_tokens: int,
    *,
    reserve_output: int = 1024,
) -> list[dict[str, Any]]:
    """
    Keeps the system prompt and trims old messages from the middle.

    Never removes the last user message if one exists.
    """
    budget = max(512, max_tokens - reserve_output)
    if estimate_tokens(messages) <= budget:
        return messages

    if not messages:
        return messages

    system_msgs = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]

    if not rest:
        return system_msgs

    tail: list[dict[str, Any]] = []
    while rest:
        candidate = system_msgs + rest
        if estimate_tokens(candidate) <= budget:
            return candidate
        if len(rest) <= 1:
            break
        rest.pop(0)

    return system_msgs + rest
