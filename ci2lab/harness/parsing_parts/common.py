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
    "web_search_query": "web_search",
    "internet_search": "web_search",
    "todo": "todo_write",
    "notebook": "notebook_edit",
    "git": "git_status",
    # Listing/search synonyms: different models (and the allow-lists of
    # some skills) use these names for the same `ls`/`grep` tool.
    "list_files": "ls",
    "list_dir": "ls",
    "listdir": "ls",
    "dir": "ls",
    "find": "glob",
    "search": "grep",
}


def map_name(name: str) -> str:
    """Map a model-supplied tool name to its canonical harness tool name.

    Args:
        name: Raw tool name as emitted by the model. Case and surrounding
            whitespace are ignored.

    Returns:
        The canonical tool name from ``NAME_MAP`` when an alias matches,
        otherwise the lower-cased, stripped input unchanged.
    """
    low = name.lower().strip()
    return NAME_MAP.get(low, low)


def new_call(name: str, arguments: dict[str, Any]) -> ToolCall:
    """Build a :class:`ToolCall` with a canonical name and normalized arguments.

    Args:
        name: Tool name to resolve through :func:`map_name`.
        arguments: Raw argument mapping to normalize for the resolved tool.

    Returns:
        A :class:`ToolCall` carrying the canonical tool name, the normalized
        arguments and a freshly generated unique ``call_id``.
    """
    tool = map_name(name)
    return ToolCall(
        name=tool,
        arguments=normalize_args_for_tool(tool, arguments),
        call_id=f"call_{uuid.uuid4().hex[:8]}",
    )


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Scan free-form text and return every top-level JSON object it contains.

    Walks the text character by character, attempting a raw JSON decode at each
    ``{`` so embedded objects are recovered even when surrounded by prose.

    Args:
        text: Text that may contain zero or more JSON objects.

    Returns:
        The decoded ``dict`` objects in the order they appear. Non-object JSON
        values (arrays, scalars) are skipped.
    """
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
    """Extract a tool's argument mapping from a parsed tool-call payload.

    Checks the common argument container keys (``arguments``/``parameters``/
    ``args``/``input``) first, parsing JSON-encoded strings when present. If
    none match, falls back to treating recognised argument keys (``path``,
    ``content``, ``command``, ``pattern``, ``old_string``) at the top level as
    the arguments, dropping the name/tool/function (and command-as-name) keys.

    Args:
        payload: A parsed JSON tool-call object.

    Returns:
        The extracted argument mapping, or an empty ``dict`` when no arguments
        can be identified.
    """
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
    """Infer a tool when a model emits only an argument object.

    Uses the presence of characteristic argument keys (e.g. ``old_string`` plus
    ``new_string`` implies ``edit_file``) to guess the intended tool when the
    payload carries no explicit name.

    Args:
        obj: A JSON object containing only tool arguments.

    Returns:
        The inferred canonical tool name, or ``None`` if no rule matches.
    """
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
    if "path" in keys and keys <= {"path", "offset", "limit", "file", "filename", "filepath"}:
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
    """Recover a tool name encoded in a payload's ``command`` field.

    Some models put the tool name in ``command`` (e.g. ``{"command": "ls"}``).
    This treats a single-token ``command`` as a tool name only when it maps to a
    known tool. A bare ``bash`` command without separate arguments is rejected so
    a genuine shell invocation is not misread as a tool name.

    Args:
        obj: A parsed JSON tool-call object.

    Returns:
        The original (unmapped) command token when it denotes a known tool,
        otherwise ``None``.
    """
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
    """Convert a parsed JSON object into a :class:`ToolCall` when possible.

    Resolves the tool name from the ``name``/``tool``/``function`` keys, the
    nested ``function.name`` field, a command-as-name field, or inference from
    bare arguments. Arguments are taken from the payload (including OpenAI-style
    ``function.arguments`` JSON strings).

    Args:
        obj: A parsed JSON object that may describe a tool call.

    Returns:
        A :class:`ToolCall` when a known tool and non-empty arguments are
        resolved, otherwise ``None``.
    """
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
    """Record a tool call for de-duplication, reporting whether it is new.

    Args:
        call: The tool call to register.
        seen: Mutable set of ``(name, serialized-arguments)`` keys already
            encountered; updated in place when ``call`` is new.

    Returns:
        ``True`` if the call had not been seen before (and was just added),
        ``False`` if it duplicates a previously remembered call.
    """
    key = (call.name, json.dumps(call.arguments, sort_keys=True, ensure_ascii=False))
    if key in seen:
        return False
    seen.add(key)
    return True
