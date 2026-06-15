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
    parse_xml_blocks,
)
from ci2lab.harness.tools.registry import TOOL_NAMES
from ci2lab.harness.types import ToolCall


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
    return False


def strip_tool_markup(text: str) -> str:
    """Quita fences, JSON tool blocks y XML del texto mostrado al usuario."""
    text = FENCED_RE.sub("", text)
    text = JSON_FENCED_RE.sub("", text)
    text = GENERIC_FENCED_RE.sub("", text)
    text = XML_TOOL_CALL_RE.sub("", text)
    text = XML_INVOKE_RE.sub("", text)
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
    "parse_fenced_blocks",
    "parse_generic_fenced_blocks",
    "parse_json_tool_objects",
    "parse_xml_blocks",
    "remember_call",
    "resolve_tool_calls",
    "strip_tool_markup",
]

