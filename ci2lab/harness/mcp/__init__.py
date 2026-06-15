"""MCP client integration — loads `.ci2lab/mcp.json` and exposes dynamic tools."""

from ci2lab.harness.mcp.config import McpServerConfig, load_mcp_config
from ci2lab.harness.mcp.session import (
    McpSessionManager,
    close_mcp_manager,
    get_mcp_manager,
    mcp_tool_id,
)

__all__ = [
    "McpServerConfig",
    "McpSessionManager",
    "close_mcp_manager",
    "get_mcp_manager",
    "load_mcp_config",
    "mcp_tool_id",
]
