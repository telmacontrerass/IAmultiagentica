"""Shared parsing helpers for tool-call extraction."""

from __future__ import annotations

import json
import uuid
from typing import Any

from ci2lab.harness.tools.arg_normalize import normalize_args_for_tool
from ci2lab.harness.tools.registry import is_known_tool
from ci2lab.harness.types import ToolCall

NAME_MAP = {
    "shell": "bash",
    "terminal": "bash",
    "command": "bash",
    "read": "read_file",
    "cat": "read_file",
    "write": "write_file",
    "edit": "edit_file",
    "fetch": "web_fetch",
    "web": "web_fetch",
    "todo": "todo_write",
    "notebook": "notebook_edit",
    "git": "git_status",
}


def map_name(name: str) -> str:
    low = name.lower().strip()
    return NAME_MAP.get(low, low)


def new_call(name: str, arguments: dict[str, Any]) -> ToolCall:
    tool = map_name(name)
    return ToolCall(
        name=tool,
        arguments=normalize_args_for_tool(tool, arguments),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
    )


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    idx = 0
    while idx < len(text):
        if text[idx] != "{":
            idx += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        if isinstance(obj, dict):
            objects.append(obj)
        idx = max(end, idx + 1)
    return objects


def args_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("arguments", "parameters", "args", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    skip_keys = {"name", "tool", "function"}
    if isinstance(payload.get("command"), str) and command_field_as_tool_name(payload):
        skip_keys.add("command")
    if any(k in payload for k in ("path", "content", "command", "pattern", "old_string")):
        return {k: v for k, v in payload.items() if k not in skip_keys}
    return {}


def infer_tool_from_bare_args(obj: dict[str, Any]) -> str | None:
    """Infer a tool when a model emits only an argument object."""
    keys = set(obj.keys())
    if "old_string" in keys and "new_string" in keys:
        return "edit_file"
    if keys & {"patch", "diff", "unified_diff"}:
        return "apply_patch"
    if "content" in keys and "path" in keys:
        return "write_file"
    if "url" in keys or "uri" in keys:
        return "web_fetch"
    if "pattern" in keys:
        return "grep"
    if "path" in keys and keys <= {
        "path", "offset", "limit", "file", "filename", "filepath"
    }:
        return "read_file"
    if "command" in keys and isinstance(obj.get("command"), str):
        command = str(obj["command"])
        if " " in command or "\n" in command:
            return "bash"
        mapped = map_name(command)
        if is_known_tool(mapped) and mapped != "bash":
            return mapped
    return None


def command_field_as_tool_name(obj: dict[str, Any]) -> str | None:
    command = obj.get("command")
    if not isinstance(command, str):
        return None
    stripped = command.strip()
    if not stripped or " " in stripped or "\n" in stripped:
        return None
    mapped = map_name(stripped)
    if not is_known_tool(mapped):
        return None
    if mapped == "bash" and not any(
        key in obj for key in ("arguments", "parameters", "args", "input")
    ):
        return None
    return stripped


def json_object_to_call(obj: dict[str, Any]) -> ToolCall | None:
    raw_name = obj.get("name") or obj.get("tool") or obj.get("function")
    if not raw_name:
        fn = obj.get("function")
        if isinstance(fn, dict):
            raw_name = fn.get("name")
    if not raw_name:
        raw_name = command_field_as_tool_name(obj)
    if not raw_name:
        raw_name = infer_tool_from_bare_args(obj)
    if not raw_name:
        return None
    name = map_name(str(raw_name))
    if not is_known_tool(name):
        return None
    args = args_from_payload(obj)
    if isinstance(fn := obj.get("function"), dict):
        fn_args = fn.get("arguments")
        if isinstance(fn_args, dict):
            args = fn_args
        elif isinstance(fn_args, str) and fn_args.strip():
            try:
                args = json.loads(fn_args)
            except json.JSONDecodeError:
                pass
    if not args and name == "bash" and "command" in obj:
        args = {"command": obj["command"]}
    if not args:
        return None
    return new_call(name, args)


def remember_call(call: ToolCall, seen: set[tuple[str, str]]) -> bool:
    key = (call.name, json.dumps(call.arguments, sort_keys=True, ensure_ascii=False))
    if key in seen:
        return False
    seen.add(key)
    return True

