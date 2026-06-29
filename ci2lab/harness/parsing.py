"""Parsing of tool invocations from the model's response."""

from __future__ import annotations

from ci2lab.harness.parsing_parts.common import (
    NAME_MAP as _NAME_MAP,
)
from ci2lab.harness.parsing_parts.common import (
    args_from_payload as _args_from_payload,
)
from ci2lab.harness.parsing_parts.common import (
    command_field_as_tool_name as _command_field_as_tool_name,
)
from ci2lab.harness.parsing_parts.common import (
    extract_json_objects as _extract_json_objects,
)
from ci2lab.harness.parsing_parts.common import (
    infer_tool_from_bare_args as _infer_tool_from_bare_args,
)
from ci2lab.harness.parsing_parts.common import (
    json_object_to_call as _json_object_to_call,
)
from ci2lab.harness.parsing_parts.common import (
    map_name as _map_name,
)
from ci2lab.harness.parsing_parts.common import (
    new_call as _new_call,
)
from ci2lab.harness.parsing_parts.common import (
    remember_call as _remember_call,
)
from ci2lab.harness.parsing_parts.fenced import (
    FENCED_RE as _FENCED_RE,
)
from ci2lab.harness.parsing_parts.fenced import (
    GENERIC_FENCED_RE as _GENERIC_FENCED_RE,
)
from ci2lab.harness.parsing_parts.fenced import (
    SHELL_FENCE_TAGS as _SHELL_FENCE_TAGS,
)
from ci2lab.harness.parsing_parts.fenced import (
    fenced_body_to_args as _fenced_body_to_args,
)
from ci2lab.harness.parsing_parts.fenced import (
    is_shell_fence_tag as _is_shell_fence_tag,
)
from ci2lab.harness.parsing_parts.fenced import (
    looks_like_shell_command as _looks_like_shell_command,
)
from ci2lab.harness.parsing_parts.fenced import (
    parse_fenced_blocks,
    parse_generic_fenced_blocks,
)
from ci2lab.harness.parsing_parts.json_tools import (
    JSON_FENCED_RE as _JSON_FENCED_RE,
)
from ci2lab.harness.parsing_parts.json_tools import (
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
)
from ci2lab.harness.parsing_parts.xml_tools import (
    XML_INVOKE_RE as _XML_INVOKE_RE,
)
from ci2lab.harness.parsing_parts.xml_tools import (
    XML_PARAM_RE as _XML_PARAM_RE,
)
from ci2lab.harness.parsing_parts.xml_tools import (
    XML_TOOL_CALL_RE as _XML_TOOL_CALL_RE,
)
from ci2lab.harness.parsing_parts.xml_tools import (
    invoke_to_call as _invoke_to_call,
)
from ci2lab.harness.parsing_parts.xml_tools import (
    normalize_dsml as _normalize_dsml,
)
from ci2lab.harness.parsing_parts.xml_tools import (
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
