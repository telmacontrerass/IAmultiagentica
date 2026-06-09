"""
Parseo de invocaciones de herramientas desde la respuesta del modelo.

Soporta:
- Function calling nativo (OpenAI / Ollama)
- Bloques fenced ```tool_name ... ```
- XML <invoke> / <tool_call> (DeepSeek, MiniMax, etc.)
- Marcado DSML de DeepSeek (normalizado a XML)
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ci2lab.harness.tools.registry import TOOL_NAMES, normalize_tool_arguments, parse_arguments
from ci2lab.harness.types import ToolCall

_FENCED_RE = re.compile(
    r"```(" + "|".join(TOOL_NAMES) + r")\s*\n([\s\S]*?)```",
    re.IGNORECASE,
)

_XML_TOOL_CALL_RE = re.compile(
    r"<(?:[\w]+:)?(?:tool_call|function_call)>\s*([\s\S]*?)</(?:[\w]+:)?(?:tool_call|function_call)>",
    re.IGNORECASE,
)
_XML_INVOKE_RE = re.compile(
    r'<invoke\s+name=["\'](\w+)["\']>\s*([\s\S]*?)</invoke>',
    re.IGNORECASE,
)
_XML_PARAM_RE = re.compile(
    r'<parameter\s+name=["\'](\w+)["\']>([\s\S]*?)</parameter>',
    re.IGNORECASE,
)

_DSML_PIPES = r"[｜|]+"


def _normalize_dsml(text: str) -> str:
    if "DSML" not in text:
        return text
    t = text
    t = re.sub(rf"<\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*tool_calls\s*>", "<tool_call>", t, flags=re.I)
    t = re.sub(rf"<\s*/\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*tool_calls\s*>", "</tool_call>", t, flags=re.I)
    t = re.sub(rf"<\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*invoke\s+name=", "<invoke name=", t, flags=re.I)
    t = re.sub(rf"<\s*/\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*invoke\s*>", "</invoke>", t, flags=re.I)
    t = re.sub(
        rf'<\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*parameter\s+name=(["\'][^"\']+["\'])[^>]*>',
        r"<parameter name=\1>",
        t,
        flags=re.I,
    )
    t = re.sub(rf"<\s*/\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*parameter\s*>", "</parameter>", t, flags=re.I)
    return t


_NAME_MAP = {
    "shell": "bash",
    "terminal": "bash",
    "command": "bash",
    "read": "read_file",
    "cat": "read_file",
    "write": "write_file",
    "edit": "edit_file",
}


def _map_name(name: str) -> str:
    low = name.lower()
    return _NAME_MAP.get(low, low)


def native_to_tool_calls(raw_calls: list[dict[str, Any]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in raw_calls:
        name = item.get("name") or item.get("function", {}).get("name", "")
        name = _map_name(name)
        if name not in TOOL_NAMES:
            continue
        args = item.get("arguments") or item.get("function", {}).get("arguments", {})
        if isinstance(args, str):
            args = parse_arguments(args)
        elif isinstance(args, dict):
            args = normalize_tool_arguments(args)
        calls.append(
            ToolCall(
                name=name,
                arguments=args,
                call_id=item.get("id") or f"call_{uuid.uuid4().hex[:8]}",
            )
        )
    return calls


def _invoke_to_call(tool_name: str, body: str) -> ToolCall | None:
    tool_name = _map_name(tool_name)
    if tool_name not in TOOL_NAMES:
        return None
    params: dict[str, Any] = {}
    for pm in _XML_PARAM_RE.finditer(body):
        params[pm.group(1)] = pm.group(2).strip()
    if not params:
        return None
    return ToolCall(
        name=tool_name,
        arguments=params,
        call_id=f"call_{uuid.uuid4().hex[:8]}",
    )


def parse_xml_blocks(text: str) -> list[ToolCall]:
    text = _normalize_dsml(text)
    calls: list[ToolCall] = []
    for block in _XML_TOOL_CALL_RE.finditer(text):
        inner = block.group(1)
        for inv in _XML_INVOKE_RE.finditer(inner):
            call = _invoke_to_call(inv.group(1), inv.group(2))
            if call:
                calls.append(call)
    for inv in _XML_INVOKE_RE.finditer(text):
        call = _invoke_to_call(inv.group(1), inv.group(2))
        if call and call not in calls:
            calls.append(call)
    return calls


def parse_fenced_blocks(text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for match in _FENCED_RE.finditer(text):
        tag = _map_name(match.group(1))
        if tag not in TOOL_NAMES:
            continue
        body = match.group(2).strip()
        args = _fenced_body_to_args(tag, body)
        calls.append(
            ToolCall(
                name=tag,
                arguments=args,
                call_id=f"call_{uuid.uuid4().hex[:8]}",
            )
        )
    return calls


def _fenced_body_to_args(tool: str, body: str) -> dict[str, Any]:
    if tool == "bash":
        return {"command": body}
    if tool == "read_file":
        if "\n" not in body and not body.startswith("{"):
            return {"path": body}
        try:
            data = json.loads(body)
            return {"path": data.get("path", body), **data}
        except json.JSONDecodeError:
            return {"path": body.splitlines()[0]}
    if tool in ("write_file", "edit_file"):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            if tool == "write_file":
                return {"path": "unknown", "content": body}
            return {"path": "unknown", "old_string": "", "new_string": body}
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
    return {"raw": body}


def resolve_tool_calls(
    text: str,
    native_calls: list[dict[str, Any]] | None,
    *,
    tool_mode: str,  # noqa: ARG001 — reservado para políticas futuras por modo
) -> list[ToolCall]:
    if native_calls:
        parsed = native_to_tool_calls(native_calls)
        if parsed:
            return parsed

    xml_calls = parse_xml_blocks(text)
    if xml_calls:
        return xml_calls

    return parse_fenced_blocks(text)


def strip_tool_markup(text: str) -> str:
    """Quita fences y XML de herramientas del texto mostrado al usuario."""
    text = _FENCED_RE.sub("", text)
    text = _XML_TOOL_CALL_RE.sub("", text)
    text = _XML_INVOKE_RE.sub("", text)
    return text.strip()
