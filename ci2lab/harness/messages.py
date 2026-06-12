"""Historial de mensajes para el bucle agéntico."""

from __future__ import annotations

import json
from typing import Any

from ci2lab.harness.types import ToolCall, ToolResult


def append_assistant_turn(
    messages: list[dict[str, Any]],
    content: str,
    tool_calls: list[ToolCall] | None = None,
) -> None:
    # Ollama rejects assistant messages with JSON null content (`<nil>`), even
    # when the message also carries tool_calls. Keep it OpenAI-compatible but
    # serialize empty assistant text as an empty string.
    msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.call_id or f"call_{i}",
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for i, tc in enumerate(tool_calls)
        ]
    messages.append(msg)


def append_tool_results(
    messages: list[dict[str, Any]],
    results: list[ToolResult],
) -> None:
    for result in results:
        messages.append({
            "role": "tool",
            "tool_call_id": result.call_id or result.tool_name,
            "content": result.content,
        })
