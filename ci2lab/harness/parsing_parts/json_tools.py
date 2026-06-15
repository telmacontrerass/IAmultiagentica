"""Native and JSON-based tool-call parsing."""

from __future__ import annotations

import json
import re
from typing import Any

from ci2lab.harness.parsing_parts.common import (
    extract_json_objects,
    json_object_to_call,
    new_call,
    remember_call,
)
from ci2lab.harness.types import ToolCall

JSON_FENCED_RE = re.compile(r"```json\s*\n([\s\S]*?)```", re.IGNORECASE)


def native_to_tool_calls(raw_calls: list[dict[str, Any]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in raw_calls:
        call = json_object_to_call(item)
        if call is None and item.get("function"):
            fn = item["function"]
            if isinstance(fn, dict) and fn.get("name"):
                args_raw = fn.get("arguments", {})
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except json.JSONDecodeError:
                        args = {"command": args_raw} if fn.get("name") == "bash" else {}
                else:
                    args = args_raw if isinstance(args_raw, dict) else {}
                call = new_call(str(fn["name"]), args)
        if call:
            calls.append(call)
    return calls


def parse_json_tool_objects(text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    seen: set[tuple[str, str]] = set()

    for block in JSON_FENCED_RE.finditer(text):
        for obj in extract_json_objects(block.group(1)):
            call = json_object_to_call(obj)
            if call and remember_call(call, seen):
                calls.append(call)

    for obj in extract_json_objects(text):
        call = json_object_to_call(obj)
        if call and remember_call(call, seen):
            calls.append(call)

    return calls

