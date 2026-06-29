"""Argument parsing and normalization for tool execution."""

from __future__ import annotations

import json
from typing import Any

from ci2lab.harness.tools.arg_normalize import normalize_args_for_tool


def normalize_tool_arguments(
    args: dict[str, Any],
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Drop ``None`` values and apply per-tool argument normalization.

    Args:
        args: Raw argument mapping as produced by the model.
        tool_name: Canonical tool name used to select tool-specific alias
            resolution. If ``None``, only ``None``-valued keys are removed.

    Returns:
        A new dict with ``None`` values stripped and, when ``tool_name`` is
        given, tool-specific key/alias normalization applied.
    """
    cleaned = {k: v for k, v in args.items() if v is not None}
    if tool_name:
        return normalize_args_for_tool(tool_name, cleaned)
    return cleaned


def parse_arguments(
    raw: str | dict[str, Any],
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Coerce raw tool arguments into a normalized argument dict.

    Accepts either an already-parsed mapping or a raw string (typically JSON).
    Strings that are not valid JSON are treated as a bare ``command`` argument
    so that shell-style invocations still produce a usable call.

    Args:
        raw: Argument payload as a mapping or string.
        tool_name: Canonical tool name forwarded to
            :func:`normalize_tool_arguments` for tool-specific normalization.

    Returns:
        The normalized argument mapping. Returns an empty dict for empty input.
    """
    if isinstance(raw, dict):
        return normalize_tool_arguments(raw, tool_name=tool_name)
    if not raw or not str(raw).strip():
        return {}
    try:
        return normalize_tool_arguments(json.loads(raw), tool_name=tool_name)
    except json.JSONDecodeError:
        return {"command": str(raw)} if raw else {}
