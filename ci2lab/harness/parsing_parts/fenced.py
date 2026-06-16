"""Markdown fenced-block tool-call parsing."""

from __future__ import annotations

import json
import re
from typing import Any

from ci2lab.harness.parsing_parts.common import (
    extract_json_objects,
    json_object_to_call,
    map_name,
    new_call,
    remember_call,
)
from ci2lab.harness.tools.bash_redirect import redirect_bash_call
from ci2lab.harness.tools.registry import TOOL_NAMES, is_known_tool
from ci2lab.harness.types import ToolCall

FENCED_RE = re.compile(
    r"```(" + "|".join(TOOL_NAMES) + r")\s*\n([\s\S]*?)```",
    re.IGNORECASE,
)
GENERIC_FENCED_RE = re.compile(
    r"```([a-zA-Z0-9_+-]*)\s*\n([\s\S]*?)```",
    re.IGNORECASE,
)
SHELL_FENCE_TAGS = frozenset({
    "bash",
    "sh",
    "shell",
    "cmd",
    "powershell",
    "ps",
    "terminal",
    "command",
})


def is_shell_fence_tag(tag: str) -> bool:
    low = tag.strip().lower()
    return low in SHELL_FENCE_TAGS or map_name(low) == "bash"


def parse_generic_fenced_blocks(text: str) -> list[ToolCall]:
    """Parse ```bash/json/...``` blocks that contain tool names + JSON."""
    calls: list[ToolCall] = []
    seen: set[tuple[str, str]] = set()

    for match in GENERIC_FENCED_RE.finditer(text):
        fence_tag = match.group(1) or ""
        body = match.group(2).strip()
        if not body:
            continue

        for obj in extract_json_objects(body):
            call = json_object_to_call(obj)
            if call and remember_call(call, seen):
                calls.append(call)

        first_line, _, rest = body.partition("\n")
        first_token = first_line.strip().split()[0] if first_line.strip() else ""
        mapped = map_name(first_token)

        if mapped in TOOL_NAMES:
            json_part = rest.strip() or " ".join(first_line.strip().split()[1:])
            if json_part:
                for obj in extract_json_objects(json_part):
                    payload = obj if "path" in obj or "content" in obj or "command" in obj else obj
                    call = new_call(mapped, payload if isinstance(payload, dict) else {})
                    if call.arguments and remember_call(call, seen):
                        calls.append(call)
                try:
                    args = json.loads(json_part)
                    if isinstance(args, dict):
                        call = new_call(mapped, args)
                        if call.arguments and remember_call(call, seen):
                            calls.append(call)
                except json.JSONDecodeError:
                    if mapped == "bash" and json_part:
                        call = redirect_bash_call(
                            new_call("bash", {"command": json_part})
                        )
                        if remember_call(call, seen):
                            calls.append(call)
                    else:
                        tool_args = fenced_body_to_args(mapped, json_part)
                        call = new_call(mapped, tool_args)
                        if call.arguments and remember_call(call, seen):
                            calls.append(call)
            continue

        if is_shell_fence_tag(fence_tag) and looks_like_shell_command(body):
            call = redirect_bash_call(new_call("bash", {"command": body}))
            if remember_call(call, seen):
                calls.append(call)

    return calls


def looks_like_shell_command(body: str) -> bool:
    stripped = body.strip()
    if not stripped or stripped.startswith("{"):
        return False
    if "\n" in stripped and not stripped.startswith(("python", "cd ", "pip ", "npm ", "git ")):
        return False
    return True


def parse_fenced_blocks(text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for match in FENCED_RE.finditer(text):
        tag = map_name(match.group(1))
        if not is_known_tool(tag):
            continue
        body = match.group(2).strip()
        args = fenced_body_to_args(tag, body)
        calls.append(redirect_bash_call(new_call(tag, args)))
    return calls


def fenced_body_to_args(tool: str, body: str) -> dict[str, Any]:
    if tool == "bash":
        return {"command": body}
    if tool in ("read_file", "read_document"):
        if "\n" not in body and not body.startswith("{"):
            return {"path": body}
        try:
            data = json.loads(body)
            return data if isinstance(data, dict) else {"path": body}
        except json.JSONDecodeError:
            return {"path": body.splitlines()[0]}
    if tool in ("write_file", "write_docx", "edit_file", "fill_docx_template"):
        try:
            data = json.loads(body)
            return data if isinstance(data, dict) else {"content": body}
        except json.JSONDecodeError:
            if tool in ("write_file", "write_docx"):
                return {"path": "unknown", "content": body}
            if tool == "fill_docx_template":
                return {"template": "", "output": "", "fields": {}}
            return {"path": "unknown", "old_string": "", "new_string": body}
    if tool == "apply_patch":
        try:
            data = json.loads(body)
            return data if isinstance(data, dict) else {"patch": body}
        except json.JSONDecodeError:
            return {"patch": body}
    if tool in ("docx_to_pdf", "pdf_to_docx"):
        try:
            data = json.loads(body)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    if tool == "grep":
        if "\n" not in body:
            return {"pattern": body}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"pattern": body}
    if tool == "glob":
        return {"pattern": body}
    if tool == "ls":
        return {"path": body or "."}
    if tool == "file_info":
        return {"path": body.strip()}
    if tool == "tree":
        if body.strip().startswith("{"):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                pass
        return {"path": body.strip() or "."}
    if tool == "inspect_file":
        if body.strip().startswith("{"):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                pass
        return {"path": body.strip()}
    if tool == "web_fetch":
        if body.startswith("http://") or body.startswith("https://"):
            return {"url": body.strip()}
        try:
            data = json.loads(body)
            return data if isinstance(data, dict) else {"url": body}
        except json.JSONDecodeError:
            return {"url": body.strip()}
    if tool == "web_search":
        try:
            data = json.loads(body)
            return data if isinstance(data, dict) else {"query": body.strip()}
        except json.JSONDecodeError:
            return {"query": body.strip()}
    if tool == "ask_user":
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"question": body}
    if tool == "todo_write":
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}
    if tool == "notebook_edit":
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}
    if tool == "git_status":
        if not body or body.strip() in {".", "{}"}:
            return {"path": "."}
        try:
            data = json.loads(body)
            return data if isinstance(data, dict) else {"path": body.strip()}
        except json.JSONDecodeError:
            return {"path": body.strip()}
    if tool == "git_diff":
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"path": body.strip()}
    if tool == "skill":
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                if "skill_name" not in data and "name" in data:
                    data["skill_name"] = data["name"]
                return data
        except json.JSONDecodeError:
            pass
        return {"skill_name": body.strip(), "args": ""}
    if tool == "mcp_call":
        try:
            data = json.loads(body)
            return data if isinstance(data, dict) else {"tool": body.strip()}
        except json.JSONDecodeError:
            return {"server": "", "tool": body.strip()}
    if tool.startswith("mcp__"):
        try:
            data = json.loads(body)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {"raw": body}
