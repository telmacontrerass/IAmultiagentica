"""XML and DSML tool-call parsing."""

from __future__ import annotations

import re
from typing import Any

from ci2lab.harness.parsing_parts.common import map_name, new_call
from ci2lab.harness.tools.registry import is_known_tool
from ci2lab.harness.types import ToolCall

DSML_PIPES = r"[｜|]+"

XML_TOOL_CALL_RE = re.compile(
    r"<(?:[\w]+:)?(?:tool_call|function_call)>\s*([\s\S]*?)</(?:[\w]+:)?(?:tool_call|function_call)>",
    re.IGNORECASE,
)
XML_INVOKE_RE = re.compile(
    r'<invoke\s+name=["\'](\w+)["\']>\s*([\s\S]*?)</invoke>',
    re.IGNORECASE,
)
XML_PARAM_RE = re.compile(
    r'<parameter\s+name=["\'](\w+)["\']>([\s\S]*?)</parameter>',
    re.IGNORECASE,
)


def normalize_dsml(text: str) -> str:
    if "DSML" not in text:
        return text
    t = text
    t = re.sub(rf"<\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*tool_calls\s*>", "<tool_call>", t, flags=re.I)
    t = re.sub(rf"<\s*/\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*tool_calls\s*>", "</tool_call>", t, flags=re.I)
    t = re.sub(rf"<\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*invoke\s+name=", "<invoke name=", t, flags=re.I)
    t = re.sub(rf"<\s*/\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*invoke\s*>", "</invoke>", t, flags=re.I)
    t = re.sub(
        rf'<\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*parameter\s+name=(["\'][^"\']+["\'])[^>]*>',
        r"<parameter name=\1>",
        t,
        flags=re.I,
    )
    t = re.sub(rf"<\s*/\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*parameter\s*>", "</parameter>", t, flags=re.I)
    return t


def invoke_to_call(tool_name: str, body: str) -> ToolCall | None:
    tool_name = map_name(tool_name)
    if not is_known_tool(tool_name):
        return None
    params: dict[str, Any] = {}
    for pm in XML_PARAM_RE.finditer(body):
        params[pm.group(1)] = pm.group(2).strip()
    if not params:
        return None
    return new_call(tool_name, params)


def parse_xml_blocks(text: str) -> list[ToolCall]:
    text = normalize_dsml(text)
    calls: list[ToolCall] = []
    for block in XML_TOOL_CALL_RE.finditer(text):
        inner = block.group(1)
        for inv in XML_INVOKE_RE.finditer(inner):
            call = invoke_to_call(inv.group(1), inv.group(2))
            if call:
                calls.append(call)
    for inv in XML_INVOKE_RE.finditer(text):
        call = invoke_to_call(inv.group(1), inv.group(2))
        if call and call not in calls:
            calls.append(call)
    return calls

