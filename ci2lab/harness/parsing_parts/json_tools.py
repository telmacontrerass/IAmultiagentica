"""Native and JSON-based tool-call parsing."""

from __future__ import annotations

import json
import re
from typing import Any

from ci2lab.harness.parsing_parts.common import (
    extract_json_objects,
    json_object_to_call,
    loads_json_lenient,
    new_call,
    remember_call,
)
from ci2lab.harness.types import ToolCall

JSON_FENCED_RE = re.compile(r"```json\s*\n([\s\S]*?)```", re.IGNORECASE)


def _calls_from_json_value(value: Any) -> list[ToolCall]:
    """Recursively find tool-call shaped objects in nested JSON values."""
    calls: list[ToolCall] = []
    if isinstance(value, dict):
        call = json_object_to_call(value)
        if call:
            calls.append(call)
        for nested in value.values():
            calls.extend(_calls_from_json_value(nested))
    elif isinstance(value, list):
        for item in value:
            calls.extend(_calls_from_json_value(item))
    return calls


def native_to_tool_calls(raw_calls: list[dict[str, Any]]) -> list[ToolCall]:
    """Convert provider-native tool-call payloads into :class:`ToolCall` objects.

    Handles both the harness's own JSON shape (via :func:`json_object_to_call`)
    and the OpenAI ``function``-wrapped form, including ``arguments`` supplied as
    a JSON-encoded string.

    Args:
        raw_calls: Native tool-call payloads as returned by the model provider.

    Returns:
        The successfully converted tool calls, preserving input order. Payloads
        that cannot be resolved are skipped.
    """
    calls: list[ToolCall] = []
    for item in raw_calls:
        call = json_object_to_call(item)
        if call is None and item.get("function"):
            fn = item["function"]
            if isinstance(fn, dict) and fn.get("name"):
                args_raw = fn.get("arguments", {})
                if isinstance(args_raw, str):
                    try:
                        args = loads_json_lenient(args_raw)
                    except json.JSONDecodeError:
                        args = {"command": args_raw} if fn.get("name") == "bash" else {}
                else:
                    args = args_raw if isinstance(args_raw, dict) else {}
                call = new_call(str(fn["name"]), args)
        if call:
            calls.append(call)
    return calls


def parse_json_tool_objects(text: str) -> list[ToolCall]:
    """Parse tool calls from JSON objects embedded in model text.

    Scans both ```` ```json ```` fenced blocks and the raw text for JSON objects,
    converting each to a tool call and de-duplicating across both passes.

    Args:
        text: Model output that may contain JSON-encoded tool calls.

    Returns:
        The distinct tool calls found, in discovery order.
    """
    calls: list[ToolCall] = []
    seen: set[tuple[str, str]] = set()

    for block in JSON_FENCED_RE.finditer(text):
        for obj in extract_json_objects(block.group(1)):
            for call in _calls_from_json_value(obj):
                if remember_call(call, seen):
                    calls.append(call)

    for obj in extract_json_objects(text):
        for call in _calls_from_json_value(obj):
            if remember_call(call, seen):
                calls.append(call)

    return calls
