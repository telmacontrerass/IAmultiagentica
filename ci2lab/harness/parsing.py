"""Parsing of tool invocations from the model's response."""

from __future__ import annotations

from ci2lab.harness.parsing_parts.common import (
    NAME_MAP as _NAME_MAP,
    args_from_payload as _args_from_payload,
    command_field_as_tool_name as _command_field_as_tool_name,
    extract_json_objects as _extract_json_objects,
    infer_tool_from_bare_args as _infer_tool_from_bare_args,
    json_object_to_call as _json_object_to_call,
    map_name as _map_name,
    new_call as _new_call,
    remember_call as _remember_call,
)
from ci2lab.harness.parsing_parts.fenced import (
    FENCED_RE as _FENCED_RE,
    GENERIC_FENCED_RE as _GENERIC_FENCED_RE,
    SHELL_FENCE_TAGS as _SHELL_FENCE_TAGS,
    fenced_body_to_args as _fenced_body_to_args,
    is_shell_fence_tag as _is_shell_fence_tag,
    looks_like_shell_command as _looks_like_shell_command,
    parse_fenced_blocks,
    parse_generic_fenced_blocks,
)
from ci2lab.harness.parsing_parts.json_tools import (
    JSON_FENCED_RE as _JSON_FENCED_RE,
    native_to_tool_calls,
    parse_json_tool_objects,
)
from ci2lab.harness.parsing_parts.resolver import (
    looks_like_unparsed_tool_attempt,
    resolve_tool_calls,
    strip_tool_markup,
)
from ci2lab.harness.parsing_parts.xml_tools import (
    DSML_PIPES as _DSML_PIPES,
    XML_INVOKE_RE as _XML_INVOKE_RE,
    XML_PARAM_RE as _XML_PARAM_RE,
    XML_TOOL_CALL_RE as _XML_TOOL_CALL_RE,
    invoke_to_call as _invoke_to_call,
    normalize_dsml as _normalize_dsml,
    parse_xml_blocks,
)

__all__ = [
    "looks_like_unparsed_tool_attempt",
    "native_to_tool_calls",
    "parse_fenced_blocks",
    "parse_generic_fenced_blocks",
    "parse_json_tool_objects",
    "parse_xml_blocks",
    "resolve_tool_calls",
    "strip_tool_markup",
]

