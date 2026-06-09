"""Recorte de historial para no superar el contexto del modelo."""

from __future__ import annotations

from typing import Any


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimación rápida (~4 caracteres por token)."""
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
    Mantiene el system prompt y recorta mensajes antiguos del medio.

    Nunca elimina el último mensaje de usuario si existe.
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

    # Conservar siempre el último turno de usuario (o el último mensaje).
    tail: list[dict[str, Any]] = []
    while rest:
        candidate = system_msgs + rest
        if estimate_tokens(candidate) <= budget:
            return candidate
        if len(rest) <= 1:
            break
        rest.pop(0)

    return system_msgs + rest
