"""Argument parsing and normalization for tool execution."""

from __future__ import annotations

import json
from typing import Any

from ci2lab.harness.tools.arg_normalize import _coerce_int, normalize_args_for_tool
from ci2lab.harness.tools.schemas_parts.builtins import (
    boolean_args_for_tool,
    integer_args_for_tool,
    required_args_for_tool,
)

#: Stringy boolean forms a model may emit for a boolean argument.
_TRUE_STRINGS = frozenset({"true", "1", "yes", "y", "on"})
_FALSE_STRINGS = frozenset({"false", "0", "no", "n", "off"})


def normalize_tool_arguments(
    args: dict[str, Any],
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Drop ``None`` values and apply per-tool argument normalization.

    When ``tool_name`` is given this also coerces the tool's schema-declared
    boolean (``"false"`` → ``False``) and integer (``"2"`` → ``2``) arguments from
    stringy forms, so a model that emits them as text does not silently invert a
    flag or crash a handler that compares/slices with the value.

    Args:
        args: Raw argument mapping as produced by the model.
        tool_name: Canonical tool name used to select tool-specific alias
            resolution. If ``None``, only ``None``-valued keys are removed.

    Returns:
        A new dict with ``None`` values stripped and, when ``tool_name`` is
        given, tool-specific key/alias normalization plus boolean and integer
        coercion applied.
    """
    cleaned = {k: v for k, v in args.items() if v is not None}
    if not tool_name:
        return cleaned
    cleaned = normalize_args_for_tool(tool_name, cleaned)
    cleaned = _coerce_boolean_args(tool_name, cleaned)
    return _coerce_integer_args(tool_name, cleaned)


def _coerce_bool(value: Any) -> Any:
    """Convert a recognized string boolean to a real ``bool``; pass others through.

    Only strings are converted (a bare ``int`` already behaves correctly under
    truthiness); an unrecognized string is left untouched rather than guessed.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    return value


def _coerce_boolean_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Coerce the tool's schema-declared boolean arguments from stringy forms."""
    bool_keys = boolean_args_for_tool(tool_name)
    if not bool_keys:
        return args
    return {key: (_coerce_bool(val) if key in bool_keys else val) for key, val in args.items()}


def _coerce_integer_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Coerce the tool's schema-declared integer arguments from digit strings.

    Schema-driven, so it covers every integer argument uniformly — including
    those (e.g. ``tree.depth``, ``inspect_file.start``) that the per-tool
    normalization never hand-coerced. Reuses :func:`_coerce_int`, which leaves
    non-digit strings and bools untouched.
    """
    int_keys = integer_args_for_tool(tool_name)
    if not int_keys:
        return args
    return {key: (_coerce_int(val) if key in int_keys else val) for key, val in args.items()}


def validate_tool_arguments(name: str, args: dict[str, Any]) -> str | None:
    """Return an actionable error if a required argument is missing, else ``None``.

    Presence-only check against the tool's schema ``required`` list: it flags an
    argument the model omitted entirely, turning what would otherwise be a cryptic
    ``KeyError`` at dispatch into a message the model can act on. It does **not**
    inspect values, so a deliberate empty string (e.g. ``content=""`` to create an
    empty file) still passes. Non-built-in tools (``mcp__*``) are not validated
    here — their schema lives on the MCP server — and return ``None``.

    Args:
        name: Canonical tool name (as it will be dispatched).
        args: The normalized argument mapping (aliases resolved, ``None`` values
            already dropped).

    Returns:
        A one-line error message naming the missing argument(s), or ``None`` when
        every required argument is present (or the tool is not a built-in).
    """
    required = required_args_for_tool(name)
    if required is None:
        return None
    missing = [key for key in required if key not in args]
    if not missing:
        return None
    missing_label = ", ".join(f"`{key}`" for key in missing)
    provided_label = ", ".join(f"`{key}`" for key in sorted(args)) or "(none)"
    return (
        f"{name} requires {missing_label} (provided: {provided_label}). "
        "Call it again including the missing argument(s)."
    )


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
