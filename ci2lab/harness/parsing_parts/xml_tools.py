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

# Qwen-Coder / Hermes-style function-call dialect: ``<function=NAME> …
# <parameter=KEY>value</parameter> … </function>`` (the name/key follow an ``=``
# rather than a ``name="…"`` attribute). Rewritten into the standard
# ``<invoke>``/``<parameter name="…">`` tags the parser already understands.
XML_FUNCTION_OPEN_RE = re.compile(
    r'<function\s*=\s*["\']?([\w.+-]+)["\']?\s*>',
    re.IGNORECASE,
)
XML_FUNCTION_CLOSE_RE = re.compile(r"</function\s*>", re.IGNORECASE)
XML_PARAM_EQ_RE = re.compile(
    r'<parameter\s*=\s*["\']?([\w.+-]+)["\']?\s*>',
    re.IGNORECASE,
)


def normalize_function_tags(text: str) -> str:
    """Rewrite the ``<function=NAME>`` tool-call dialect into standard XML tags.

    Some Qwen-Coder and Hermes-style templates emit tool calls as
    ``<function=ls><parameter=path>.</parameter></function>`` instead of the
    ``<invoke name="ls"><parameter name="path">.</parameter></invoke>`` form the
    XML parser expects. This converts the ``<function=…>``/``</function>`` and
    ``<parameter=…>`` tags so the existing :data:`XML_INVOKE_RE`/
    :data:`XML_PARAM_RE` parsers can pick them up. The text is returned unchanged
    when it contains no such markup.

    Args:
        text: Raw model output that may contain the ``<function=…>`` dialect.

    Returns:
        The text with any ``<function=…>`` tool-call tags normalized to standard
        XML ``<invoke>``/``<parameter name="…">`` tags.
    """
    lowered = text.lower()
    if "<function" not in lowered and "<parameter=" not in lowered:
        return text
    t = XML_FUNCTION_OPEN_RE.sub(lambda m: f'<invoke name="{m.group(1)}">', text)
    t = XML_FUNCTION_CLOSE_RE.sub("</invoke>", t)
    t = XML_PARAM_EQ_RE.sub(lambda m: f'<parameter name="{m.group(1)}">', t)
    return t


def normalize_dsml(text: str) -> str:
    """Rewrite DeepSeek DSML tool-call markup into standard XML tool tags.

    DeepSeek models wrap tool calls in ``<｜DSML｜tool_calls>`` style tags using
    full-width pipe characters. This converts those tags (and the matching
    ``invoke``/``parameter`` tags) into the plain ``<tool_call>``/``<invoke>``/
    ``<parameter>`` forms the XML parser understands. The text is returned
    unchanged when it contains no ``DSML`` marker.

    Args:
        text: Raw model output that may contain DSML markup.

    Returns:
        The text with any DSML tool-call tags normalized to standard XML.
    """
    if "DSML" not in text:
        return text
    t = text
    t = re.sub(
        rf"<\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*tool_calls\s*>", "<tool_call>", t, flags=re.I
    )
    t = re.sub(
        rf"<\s*/\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*tool_calls\s*>",
        "</tool_call>",
        t,
        flags=re.I,
    )
    t = re.sub(
        rf"<\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*invoke\s+name=", "<invoke name=", t, flags=re.I
    )
    t = re.sub(
        rf"<\s*/\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*invoke\s*>", "</invoke>", t, flags=re.I
    )
    t = re.sub(
        rf'<\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*parameter\s+name=(["\'][^"\']+["\'])[^>]*>',
        r"<parameter name=\1>",
        t,
        flags=re.I,
    )
    t = re.sub(
        rf"<\s*/\s*{DSML_PIPES}\s*DSML\s*{DSML_PIPES}\s*parameter\s*>",
        "</parameter>",
        t,
        flags=re.I,
    )
    return t


def invoke_to_call(tool_name: str, body: str) -> ToolCall | None:
    """Build a tool call from an ``<invoke>`` tool name and its inner body.

    Extracts ``<parameter name=...>`` values from ``body`` as the call's
    arguments.

    Args:
        tool_name: Tool name from the ``<invoke name=...>`` tag.
        body: Inner XML of the ``<invoke>`` element holding ``<parameter>`` tags.

    Returns:
        A :class:`ToolCall` for a known tool with at least one parameter,
        otherwise ``None``.
    """
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
    """Parse tool calls from XML/DSML ``<invoke>`` markup in model text.

    Normalizes DSML markup and the ``<function=…>`` dialect first, then extracts
    ``<invoke>`` elements both inside ``<tool_call>``/``<function_call>`` wrappers
    and at the top level, skipping duplicates discovered by the second pass.

    Args:
        text: Model output that may contain XML or DSML tool-call markup.

    Returns:
        The tool calls parsed from the markup, in discovery order.
    """
    text = normalize_dsml(text)
    text = normalize_function_tags(text)
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
