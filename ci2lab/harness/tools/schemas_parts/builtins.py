"""Aggregation of the built-in OpenAI-compatible function schemas.

Concatenates the per-category schema lists (runtime, explore, edit, workflow,
integrations) into :data:`FUNCTION_SCHEMAS` and exposes
:func:`get_function_schemas`, which merges in dynamic MCP tools and applies any
active skill's tool allow-list. Also re-exports :data:`TOOL_NAMES` and
:func:`is_known_tool` from the registry for convenience.
"""

from __future__ import annotations

from typing import Any

from ci2lab.harness.tools.schemas_parts.edit import EDIT_SCHEMAS
from ci2lab.harness.tools.schemas_parts.explore import EXPLORE_SCHEMAS
from ci2lab.harness.tools.schemas_parts.integrations import INTEGRATIONS_SCHEMAS
from ci2lab.harness.tools.schemas_parts.registry import TOOL_NAMES, is_known_tool
from ci2lab.harness.tools.schemas_parts.runtime import RUNTIME_SCHEMAS
from ci2lab.harness.tools.schemas_parts.workflow import WORKFLOW_SCHEMAS

#: All built-in OpenAI-compatible function schemas, in tool-category order.
FUNCTION_SCHEMAS: list[dict[str, Any]] = [
    *RUNTIME_SCHEMAS,
    *EXPLORE_SCHEMAS,
    *EDIT_SCHEMAS,
    *WORKFLOW_SCHEMAS,
    *INTEGRATIONS_SCHEMAS,
]

#: Canonical tool name -> its schema's required argument names. Derived from
#: :data:`FUNCTION_SCHEMAS` so the model-facing contract and argument validation
#: can never drift apart.
REQUIRED_ARGS: dict[str, list[str]] = {
    schema["function"]["name"]: list(schema["function"].get("parameters", {}).get("required", []))
    for schema in FUNCTION_SCHEMAS
    if "name" in schema.get("function", {})
}


def required_args_for_tool(name: str) -> list[str] | None:
    """Return a built-in tool's required argument names, or ``None`` if unknown.

    ``None`` (rather than an empty list) signals that ``name`` is not a built-in
    tool — e.g. a dynamic ``mcp__*`` tool whose schema lives on the MCP server —
    so callers can skip built-in argument validation for it.

    Args:
        name: Canonical tool name.

    Returns:
        The list of required argument names (possibly empty), or ``None`` when
        ``name`` is not a built-in tool.
    """
    return REQUIRED_ARGS.get(name)


#: Canonical tool name -> its top-level boolean argument names. Only top-level
#: properties are considered (a boolean nested inside an object argument is
#: passed through whole), and the mapping is derived from :data:`FUNCTION_SCHEMAS`
#: so it stays in sync with the schemas automatically.
BOOLEAN_ARGS: dict[str, set[str]] = {
    schema["function"]["name"]: {
        prop
        for prop, spec in schema["function"].get("parameters", {}).get("properties", {}).items()
        if isinstance(spec, dict) and spec.get("type") == "boolean"
    }
    for schema in FUNCTION_SCHEMAS
    if "name" in schema.get("function", {})
}


def boolean_args_for_tool(name: str) -> set[str]:
    """Return a built-in tool's top-level boolean argument names.

    Used to coerce string booleans (e.g. ``"false"``) that a model may emit into
    real ``bool`` values before dispatch — without it, ``"false"`` is a truthy
    non-empty string and silently inverts the flag.

    Args:
        name: Canonical tool name.

    Returns:
        The set of boolean argument names (empty for a tool with none, or one
        that is not a built-in).
    """
    return BOOLEAN_ARGS.get(name, set())


def get_function_schemas(config: Any | None = None) -> list[dict[str, Any]]:
    """Build the OpenAI function schema list for the current run.

    Combines the static built-in tool schemas with any dynamic MCP tools
    discovered for ``config.cwd``. When a skill restricts the allowed tools,
    the result is filtered down to that allow-list (canonicalising synonyms so
    a differently named entry still resolves to the correct schema). When the
    configuration disables the write tools (``write_tools_enabled=False``),
    their schemas are removed as well: offering a tool the executor is
    guaranteed to block only invites doomed calls.

    Args:
        config: Optional run configuration. When ``None``, only the built-in
            :data:`FUNCTION_SCHEMAS` are returned. Otherwise it supplies the
            workspace ``cwd`` used to connect to MCP servers, the optional
            ``skill_allowed_tools`` allow-list, and ``write_tools_enabled``.

    Returns:
        A list of OpenAI-compatible function schema dictionaries, possibly
        filtered to the active skill's allowed tools and write enablement.
    """
    schemas: list[dict[str, Any]] = list(FUNCTION_SCHEMAS)
    if config is not None:
        from ci2lab.harness.mcp.session import get_mcp_manager

        mgr = get_mcp_manager(config.cwd, connect=True)
        schemas.extend(mgr.build_function_schemas())
    if config is not None and config.skill_allowed_tools is not None:
        # Canonicalize synonyms (list_files→ls, etc.) so that an allow-list
        # written with a different name still exposes the correct schema to the model.
        from ci2lab.harness.parsing_parts.common import map_name

        allowed = {map_name(t) for t in config.skill_allowed_tools}
        schemas = [
            schema
            for schema in schemas
            if map_name(schema.get("function", {}).get("name", "")) in allowed
        ]
    if config is not None and not getattr(config, "write_tools_enabled", True):
        # Same set the executor enforces (`execute_write_tool`), so the schemas
        # offered to the model and the blocking behaviour can never disagree.
        from ci2lab.harness.security.write_permissions import WRITE_TOOLS

        schemas = [
            schema
            for schema in schemas
            if schema.get("function", {}).get("name", "") not in WRITE_TOOLS
        ]
    return schemas
