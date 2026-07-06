"""High-level parser orchestration and display cleanup."""

from __future__ import annotations

import json
import re
from typing import Any

from ci2lab.harness.parsing_parts.common import (
    args_from_payload,
    command_field_as_tool_name,
    extract_json_objects,
    infer_tool_from_bare_args,
    json_object_to_call,
    map_name,
    new_call,
    remember_call,
)
from ci2lab.harness.parsing_parts.fenced import (
    FENCED_RE,
    GENERIC_FENCED_RE,
    SHELL_FENCE_TAGS,
    fenced_body_to_args,
    is_shell_fence_tag,
    looks_like_shell_command,
    parse_fenced_blocks,
    parse_generic_fenced_blocks,
)
from ci2lab.harness.parsing_parts.json_tools import (
    JSON_FENCED_RE,
    native_to_tool_calls,
    parse_json_tool_objects,
)
from ci2lab.harness.parsing_parts.xml_tools import (
    DSML_PIPES,
    XML_INVOKE_RE,
    XML_PARAM_RE,
    XML_TOOL_CALL_RE,
    invoke_to_call,
    normalize_dsml,
    normalize_function_tags,
    parse_xml_blocks,
)
from ci2lab.harness.tools.registry import TOOL_NAMES
from ci2lab.harness.types import ToolCall

_TEXT_TOOL_NAME_JSON_RE = re.compile(
    r"(?:^|\n)\s*(?:modelo:\s*)?(?P<name>[a-zA-Z0-9_+-]+)\s*\n(?P<body>\{[\s\S]*?\})",
    re.IGNORECASE,
)

# A model sometimes writes a call as plain text in a key=value or call style —
# `write_file path='f.txt' content='...'` or `write_file(path="f.txt", ...)` —
# which none of the structured parsers accept. Match a known tool name at the
# start of a line followed (optionally through `(`) by an `identifier=` so the
# loop can nudge the model back to a real tool-call format instead of mistaking
# the narration for a finished answer. The word boundary after the name keeps it
# from firing on prose that merely embeds a tool name.
_TEXT_TOOL_KV_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    + "|".join(re.escape(name) for name in sorted(TOOL_NAMES))
    + r")\b\s*\(?\s*[A-Za-z_]\w*\s*=",
    re.IGNORECASE,
)


def _parse_text_tool_name_plus_json(text: str) -> list[ToolCall]:
    """Parse calls written as a bare tool name on one line then a JSON body."""
    calls: list[ToolCall] = []
    seen: set[tuple[str, str]] = set()
    for match in _TEXT_TOOL_NAME_JSON_RE.finditer(text):
        name = map_name(match.group("name"))
        if name not in TOOL_NAMES:
            continue
        body = match.group("body").strip()
        try:
            args = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(args, dict):
            continue
        call = new_call(name, args)
        if call.arguments and remember_call(call, seen):
            calls.append(call)
    return calls


def resolve_tool_calls(
    text: str,
    native_calls: list[dict[str, Any]] | None,
    *,
    tool_mode: str,
) -> list[ToolCall]:
    """Resolve tool calls from a model turn, trying each parsing strategy in turn.

    Native provider calls take priority; when absent (or unparseable) the text is
    run through the XML, fenced-block, JSON-object, text-name-plus-JSON and
    generic-fenced parsers in order, returning the first non-empty result.

    Args:
        text: The model's textual output for the turn.
        native_calls: Provider-native tool-call payloads, or ``None``/empty when
            the provider returned none.
        tool_mode: The active tool-calling mode (e.g. ``"native"``); accepted for
            caller context and forward compatibility.

    Returns:
        The resolved tool calls, or an empty list when none are found.
    """
    if native_calls:
        parsed = native_to_tool_calls(native_calls)
        if parsed:
            return parsed

    for parser in (
        parse_xml_blocks,
        parse_fenced_blocks,
        parse_json_tool_objects,
        _parse_text_tool_name_plus_json,
        parse_generic_fenced_blocks,
    ):
        parsed = parser(text)
        if parsed:
            return parsed

    return []


def looks_like_unparsed_tool_attempt(text: str) -> bool:
    """True when the model probably meant to call a tool but nothing was parsed.

    Used by the loop to nudge the model back to a valid tool-call format instead
    of treating malformed-but-tool-shaped narration as a finished answer. Returns
    ``False`` immediately if a real tool call can be resolved; otherwise looks for
    JSON fences, name/command literals naming known tools, fenced shell blocks, or
    ``tool path='...'`` key=value prose.

    Args:
        text: The model's textual output to inspect.

    Returns:
        ``True`` if the text resembles an unparsed tool-call attempt.
    """
    if resolve_tool_calls(text, [], tool_mode="native"):
        return False
    lowered = text.lower()
    if "```json" in lowered and (
        '"name"' in lowered
        or '"command"' in lowered
        or '"old_string"' in lowered
        or '"path"' in lowered
    ):
        return True
    if re.search(
        r'["\'](?:name|command)["\']\s*:\s*["\'](?:' + "|".join(TOOL_NAMES) + r')["\']',
        lowered,
    ):
        return True
    for tool in TOOL_NAMES:
        if re.search(rf"```(?:bash|sh|json)?\s*\n\s*{tool}\b", lowered):
            return True
    # `write_file path='...'` / `read_file(path=...)` style — a tool call typed
    # as prose. Checked against the original text (the patterns are
    # case-insensitive via the tool names) so a key=value call is recovered.
    if _TEXT_TOOL_KV_RE.search(text):
        return True
    return False


def strip_tool_markup(text: str) -> str:
    """Strip fences, JSON tool blocks and XML from the text shown to the user.

    Removes tool-call markup (tool/generic/JSON fences, XML tool-call and invoke
    tags, and any bare JSON objects that parse to a tool call) so only the
    user-facing prose remains.

    Args:
        text: The model's raw output.

    Returns:
        The text with tool-call markup removed and surrounding whitespace
        stripped.
    """
    text = normalize_function_tags(text)
    text = FENCED_RE.sub("", text)
    text = JSON_FENCED_RE.sub("", text)
    text = GENERIC_FENCED_RE.sub("", text)
    text = XML_TOOL_CALL_RE.sub("", text)
    text = XML_INVOKE_RE.sub("", text)
    # Drop any orphan closing wrappers left by the ``<function=…>`` dialect
    # (e.g. a trailing ``</tool_call>`` with no matching opener).
    text = re.sub(
        r"</(?:tool_call|function_call|function|invoke)\s*>", "", text, flags=re.IGNORECASE
    )
    for obj in extract_json_objects(text):
        if json_object_to_call(obj):
            text = text.replace(json.dumps(obj), "")
    return text.strip()


__all__ = [
    "DSML_PIPES",
    "FENCED_RE",
    "GENERIC_FENCED_RE",
    "JSON_FENCED_RE",
    "SHELL_FENCE_TAGS",
    "TOOL_NAMES",
    "XML_INVOKE_RE",
    "XML_PARAM_RE",
    "XML_TOOL_CALL_RE",
    "args_from_payload",
    "command_field_as_tool_name",
    "extract_json_objects",
    "fenced_body_to_args",
    "infer_tool_from_bare_args",
    "invoke_to_call",
    "is_shell_fence_tag",
    "json_object_to_call",
    "looks_like_shell_command",
    "looks_like_unparsed_tool_attempt",
    "map_name",
    "native_to_tool_calls",
    "new_call",
    "normalize_dsml",
    "normalize_function_tags",
    "parse_fenced_blocks",
    "parse_generic_fenced_blocks",
    "parse_json_tool_objects",
    "parse_xml_blocks",
    "remember_call",
    "resolve_tool_calls",
    "strip_tool_markup",
]
