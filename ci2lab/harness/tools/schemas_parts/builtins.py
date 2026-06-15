"""Built-in OpenAI-compatible function schemas."""

from __future__ import annotations

from typing import Any

from ci2lab.harness.tools.schemas_parts.edit import EDIT_SCHEMAS
from ci2lab.harness.tools.schemas_parts.explore import EXPLORE_SCHEMAS
from ci2lab.harness.tools.schemas_parts.integrations import INTEGRATIONS_SCHEMAS
from ci2lab.harness.tools.schemas_parts.registry import TOOL_NAMES, is_known_tool
from ci2lab.harness.tools.schemas_parts.runtime import RUNTIME_SCHEMAS
from ci2lab.harness.tools.schemas_parts.workflow import WORKFLOW_SCHEMAS

FUNCTION_SCHEMAS: list[dict[str, Any]] = [
    *RUNTIME_SCHEMAS,
    *EXPLORE_SCHEMAS,
    *EDIT_SCHEMAS,
    *WORKFLOW_SCHEMAS,
    *INTEGRATIONS_SCHEMAS,
]


def get_function_schemas(config: Any | None = None) -> list[dict[str, Any]]:
    """Built-in tools plus dynamic MCP tools, optionally filtered by an active skill."""
    schemas: list[dict[str, Any]] = list(FUNCTION_SCHEMAS)
    if config is not None:
        from ci2lab.harness.mcp.session import get_mcp_manager

        mgr = get_mcp_manager(config.cwd, connect=True)
        schemas.extend(mgr.build_function_schemas())
    if config is not None and config.skill_allowed_tools is not None:
        allowed = config.skill_allowed_tools
        schemas = [
            schema
            for schema in schemas
            if schema.get("function", {}).get("name") in allowed
        ]
    return schemas
