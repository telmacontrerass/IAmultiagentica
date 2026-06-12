"""
Parseo de invocaciones de herramientas desde la respuesta del modelo.

Soporta:
- Function calling nativo (OpenAI / Ollama)
- Bloques fenced ```tool_name ... ```
- Bloques ```json con {"name": ..., "arguments": ...}
- JSON inline suelto con name/arguments/parameters
- Fences genéricos (bash/json/python) con tool + JSON dentro
- XML <invoke> / <tool_call> (DeepSeek, MiniMax, etc.)
- Marcado DSML de DeepSeek (normalizado a XML)
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ci2lab.harness.tools.arg_normalize import normalize_args_for_tool
from ci2lab.harness.tools.registry import TOOL_NAMES, is_known_tool
from ci2lab.harness.types import ToolCall

_FENCED_RE = re.compile(
    r"```(" + "|".join(TOOL_NAMES) + r")\s*\n([\s\S]*?)```",
    re.IGNORECASE,
)
_JSON_FENCED_RE = re.compile(r"```json\s*\n([\s\S]*?)```", re.IGNORECASE)
_GENERIC_FENCED_RE = re.compile(
    r"```([a-zA-Z0-9_+-]*)\s*\n([\s\S]*?)```",
    re.IGNORECASE,
)
# Solo estas etiquetas de fence pueden promover el cuerpo a bash (V-01 red team).
_SHELL_FENCE_TAGS = frozenset({
    "bash",
    "sh",
    "shell",
    "cmd",
    "powershell",
    "ps",
    "terminal",
    "command",
})

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

_NAME_MAP = {
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


def _map_name(name: str) -> str:
    low = name.lower().strip()
    return _NAME_MAP.get(low, low)


def _new_call(name: str, arguments: dict[str, Any]) -> ToolCall:
    tool = _map_name(name)
    return ToolCall(
        name=tool,
        arguments=normalize_args_for_tool(tool, arguments),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
    )


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
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


def _args_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
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
    if any(k in payload for k in ("path", "content", "command", "pattern", "old_string")):
        return {k: v for k, v in payload.items() if k != "name"}
    return {}


def _json_object_to_call(obj: dict[str, Any]) -> ToolCall | None:
    raw_name = obj.get("name") or obj.get("tool") or obj.get("function")
    if not raw_name:
        fn = obj.get("function")
        if isinstance(fn, dict):
            raw_name = fn.get("name")
    if not raw_name:
        return None
    name = _map_name(str(raw_name))
    if not is_known_tool(name):
        return None
    args = _args_from_payload(obj)
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
    return _new_call(name, args)


def native_to_tool_calls(raw_calls: list[dict[str, Any]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in raw_calls:
        call = _json_object_to_call(item)
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
                call = _new_call(str(fn["name"]), args)
        if call:
            calls.append(call)
    return calls


def _invoke_to_call(tool_name: str, body: str) -> ToolCall | None:
    tool_name = _map_name(tool_name)
    if not is_known_tool(tool_name):
        return None
    params: dict[str, Any] = {}
    for pm in _XML_PARAM_RE.finditer(body):
        params[pm.group(1)] = pm.group(2).strip()
    if not params:
        return None
    return _new_call(tool_name, params)


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


def parse_json_tool_objects(text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    seen: set[tuple[str, str]] = set()

    for block in _JSON_FENCED_RE.finditer(text):
        for obj in _extract_json_objects(block.group(1)):
            call = _json_object_to_call(obj)
            if call and _remember_call(call, seen):
                calls.append(call)

    for obj in _extract_json_objects(text):
        call = _json_object_to_call(obj)
        if call and _remember_call(call, seen):
            calls.append(call)

    return calls


def _is_shell_fence_tag(tag: str) -> bool:
    low = tag.strip().lower()
    return low in _SHELL_FENCE_TAGS or _map_name(low) == "bash"


def parse_generic_fenced_blocks(text: str) -> list[ToolCall]:
    """Parse ```bash/json/...``` blocks that contain tool names + JSON."""
    calls: list[ToolCall] = []
    seen: set[tuple[str, str]] = set()

    for match in _GENERIC_FENCED_RE.finditer(text):
        fence_tag = match.group(1) or ""
        body = match.group(2).strip()
        if not body:
            continue

        for obj in _extract_json_objects(body):
            call = _json_object_to_call(obj)
            if call and _remember_call(call, seen):
                calls.append(call)

        first_line, _, rest = body.partition("\n")
        first_token = first_line.strip().split()[0] if first_line.strip() else ""
        mapped = _map_name(first_token)

        if mapped in TOOL_NAMES:
            json_part = rest.strip() or " ".join(first_line.strip().split()[1:])
            if json_part:
                for obj in _extract_json_objects(json_part):
                    payload = obj if "path" in obj or "content" in obj or "command" in obj else obj
                    call = _new_call(mapped, payload if isinstance(payload, dict) else {})
                    if call.arguments and _remember_call(call, seen):
                        calls.append(call)
                try:
                    args = json.loads(json_part)
                    if isinstance(args, dict):
                        call = _new_call(mapped, args)
                        if call.arguments and _remember_call(call, seen):
                            calls.append(call)
                except json.JSONDecodeError:
                    if mapped == "bash" and json_part:
                        call = _new_call("bash", {"command": json_part})
                        if _remember_call(call, seen):
                            calls.append(call)
            continue

        if _is_shell_fence_tag(fence_tag) and _looks_like_shell_command(body):
            call = _new_call("bash", {"command": body})
            if _remember_call(call, seen):
                calls.append(call)

    return calls


def _looks_like_shell_command(body: str) -> bool:
    stripped = body.strip()
    if not stripped or stripped.startswith("{"):
        return False
    if "\n" in stripped and not stripped.startswith(("python", "cd ", "pip ", "npm ", "git ")):
        return False
    return True


def _remember_call(call: ToolCall, seen: set[tuple[str, str]]) -> bool:
    key = (call.name, json.dumps(call.arguments, sort_keys=True, ensure_ascii=False))
    if key in seen:
        return False
    seen.add(key)
    return True


def parse_fenced_blocks(text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for match in _FENCED_RE.finditer(text):
        tag = _map_name(match.group(1))
        if not is_known_tool(tag):
            continue
        body = match.group(2).strip()
        args = _fenced_body_to_args(tag, body)
        calls.append(_new_call(tag, args))
    return calls


def _fenced_body_to_args(tool: str, body: str) -> dict[str, Any]:
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
    if tool in ("write_file", "edit_file"):
        try:
            data = json.loads(body)
            return data if isinstance(data, dict) else {"content": body}
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


def resolve_tool_calls(
    text: str,
    native_calls: list[dict[str, Any]] | None,
    *,
    tool_mode: str,  # noqa: ARG001
) -> list[ToolCall]:
    if native_calls:
        parsed = native_to_tool_calls(native_calls)
        if parsed:
            return parsed

    for parser in (
        parse_xml_blocks,
        parse_fenced_blocks,
        parse_json_tool_objects,
        parse_generic_fenced_blocks,
    ):
        parsed = parser(text)
        if parsed:
            return parsed

    return []


def looks_like_unparsed_tool_attempt(text: str) -> bool:
    """True when the model probably meant to call a tool but nothing was parsed."""
    if resolve_tool_calls(text, [], tool_mode="native"):
        return False
    lowered = text.lower()
    if "```json" in lowered and '"name"' in lowered:
        return True
    if re.search(r'["\']name["\']\s*:\s*["\'](?:' + "|".join(TOOL_NAMES) + r')["\']', lowered):
        return True
    for tool in TOOL_NAMES:
        if re.search(rf"```(?:bash|sh|json)?\s*\n\s*{tool}\b", lowered):
            return True
    return False


def strip_tool_markup(text: str) -> str:
    """Quita fences, JSON tool blocks y XML del texto mostrado al usuario."""
    text = _FENCED_RE.sub("", text)
    text = _JSON_FENCED_RE.sub("", text)
    text = _GENERIC_FENCED_RE.sub("", text)
    text = _XML_TOOL_CALL_RE.sub("", text)
    text = _XML_INVOKE_RE.sub("", text)
    for obj in _extract_json_objects(text):
        if _json_object_to_call(obj):
            text = text.replace(json.dumps(obj), "")
    return text.strip()
