"""MCP session manager: connect servers and expose tools to the harness."""

from __future__ import annotations

import json
import re
from typing import Any

from ci2lab.harness.mcp.client import McpClient, McpTool
from ci2lab.harness.mcp.config import McpServerConfig, load_mcp_config


def mcp_tool_id(server: str, tool: str) -> str:
    """Build the harness-facing tool id for an MCP tool.

    Non-identifier characters in both names are replaced with underscores so the
    id is a valid function name.

    Args:
        server: The MCP server name.
        tool: The server-side tool name.

    Returns:
        An id of the form ``mcp__<server>__<tool>``.
    """
    safe_server = re.sub(r"[^a-zA-Z0-9_]", "_", server)
    safe_tool = re.sub(r"[^a-zA-Z0-9_]", "_", tool)
    return f"mcp__{safe_server}__{safe_tool}"


def parse_mcp_tool_id(tool_id: str) -> tuple[str, str] | None:
    """Split an ``mcp__<server>__<tool>`` id into its server and tool parts.

    Args:
        tool_id: A tool id produced by :func:`mcp_tool_id`.

    Returns:
        A ``(server, tool)`` tuple, or ``None`` if ``tool_id`` is not a
        well-formed MCP tool id.
    """
    if not tool_id.startswith("mcp__"):
        return None
    parts = tool_id.split("__", 2)
    if len(parts) != 3:
        return None
    return parts[1], parts[2]


class McpSessionManager:
    """Manage MCP server connections and expose their tools to the harness.

    Loads server configs for a workspace, connects each server, aggregates the
    advertised tools and routes tool calls to the right client.
    """

    def __init__(self, cwd: str) -> None:
        """Initialize an (unconnected) manager bound to a workspace.

        Args:
            cwd: The workspace root whose MCP config governs this session.
        """
        self.cwd = cwd
        self._clients: dict[str, McpClient] = {}
        self._tools: list[McpTool] = []
        self._tool_index: dict[str, tuple[str, str]] = {}
        self._errors: list[str] = []

    @property
    def tools(self) -> list[McpTool]:
        """A snapshot copy of all tools advertised by connected servers."""
        return list(self._tools)

    @property
    def errors(self) -> list[str]:
        """A snapshot copy of connection errors recorded during :meth:`connect_all`."""
        return list(self._errors)

    def connect_all(self) -> None:
        """Reconnect every configured server, collecting tools and errors.

        Any existing connections are closed first. Per-server connection failures
        are captured in :attr:`errors` rather than raised.
        """
        self.close()
        configs = load_mcp_config(self.cwd)
        for cfg in configs:
            client = McpClient(
                server_name=cfg.name,
                command=cfg.command,
                args=cfg.args,
                env=cfg.env,
                cwd=cfg.cwd or self.cwd,
            )
            try:
                client.connect()
                self._clients[cfg.name] = client
                self._tools.extend(client.tools)
                for tool in client.tools:
                    tid = mcp_tool_id(tool.server, tool.name)
                    self._tool_index[tid] = (tool.server, tool.name)
            except Exception as exc:
                self._errors.append(f"{cfg.name}: {exc}")
                client.close()

    def close(self) -> None:
        """Close all client connections and clear cached tools and indexes."""
        for client in self._clients.values():
            client.close()
        self._clients.clear()
        self._tools.clear()
        self._tool_index.clear()

    def _client_for_server(self, server: str) -> McpClient | None:
        """Find the connected client for a server name (exact or sanitized match)."""
        if server in self._clients:
            return self._clients[server]
        for name, client in self._clients.items():
            if re.sub(r"[^a-zA-Z0-9_]", "_", name) == server:
                return client
        return None

    def call(self, server: str, tool: str, arguments: dict[str, Any]) -> str:
        """Invoke a tool on a named server, returning its result or an error string.

        Args:
            server: Target server name.
            tool: Server-side tool name.
            arguments: Arguments to pass to the tool.

        Returns:
            The tool's textual result, or an ``Error:`` message if the server is
            not connected or the call raises.
        """
        client = self._client_for_server(server)
        if client is None:
            return f"Error: MCP server `{server}` is not connected"
        try:
            return client.call_tool(tool, arguments)
        except Exception as exc:
            return f"Error: MCP call failed: {exc}"

    def call_by_id(self, tool_id: str, arguments: dict[str, Any]) -> str:
        """Invoke a tool addressed by its harness-facing ``mcp__...`` id.

        Resolves the id from the tool index when known, otherwise parses it and
        resolves the (possibly sanitized) tool name against the server's tools.

        Args:
            tool_id: A tool id produced by :func:`mcp_tool_id`.
            arguments: Arguments to pass to the tool.

        Returns:
            The tool's textual result, or an ``Error:`` message when the id is
            invalid or the server/tool cannot be resolved.
        """
        indexed = self._tool_index.get(tool_id)
        if indexed:
            server, tool = indexed
            return self.call(server, tool, arguments)
        parsed = parse_mcp_tool_id(tool_id)
        if not parsed:
            return f"Error: invalid MCP tool id `{tool_id}`"
        server, tool = parsed
        client = self._client_for_server(server)
        if client is None:
            return f"Error: MCP server `{server}` is not connected"
        real_name = self._resolve_tool_name(client, tool)
        if not real_name:
            return f"Error: MCP tool `{tool}` not found on server `{server}`"
        return self.call(server, real_name, arguments)

    @staticmethod
    def _resolve_tool_name(client: McpClient, sanitized: str) -> str | None:
        """Map a sanitized tool-id segment back to the client's real tool name."""
        for t in client.tools:
            if mcp_tool_id(client.server_name, t.name) == f"mcp__{client.server_name}__{sanitized}":
                return t.name
            if re.sub(r"[^a-zA-Z0-9_]", "_", t.name) == sanitized:
                return t.name
        return None

    def build_function_schemas(self) -> list[dict[str, Any]]:
        """Build OpenAI-style function schemas for all connected MCP tools.

        Returns:
            One ``{"type": "function", "function": {...}}`` schema per tool, with
            the harness-facing id as the function name and the tool's input schema
            (properties/required) as parameters.
        """
        schemas: list[dict[str, Any]] = []
        for tool in self._tools:
            tid = mcp_tool_id(tool.server, tool.name)
            schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
            properties = schema.get("properties") or {}
            required = schema.get("required") or []
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tid,
                        "description": (f"[MCP:{tool.server}] {tool.description or tool.name}")[
                            :500
                        ],
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                }
            )
        return schemas

    def format_status(self) -> str:
        """Render a Markdown summary of connected servers, tools and errors.

        Returns:
            A Markdown block listing connected servers, advertised tools and any
            connection failures, or an empty string when there is nothing to
            report.
        """
        if not self._tools and not self._errors:
            return ""
        lines = ["## MCP servers"]
        if self._clients:
            lines.append("Connected: " + ", ".join(sorted(self._clients.keys())))
        for tool in self._tools:
            lines.append(f"- `{mcp_tool_id(tool.server, tool.name)}`: {tool.name}")
        for err in self._errors:
            lines.append(f"- (failed) {err}")
        return "\n".join(lines)


# Per-run cache keyed by cwd
_managers: dict[str, McpSessionManager] = {}


def get_mcp_manager(cwd: str, *, connect: bool = True) -> McpSessionManager:
    """Return the cached session manager for a workspace, creating it if needed.

    Managers are cached per ``cwd``. When ``connect`` is set, a freshly created
    manager connects immediately, and an existing-but-disconnected manager
    reconnects if the workspace still declares MCP servers.

    Args:
        cwd: The workspace root used as the cache key.
        connect: Whether to (re)connect servers as part of this call.

    Returns:
        The shared :class:`McpSessionManager` for ``cwd``.
    """
    key = str(cwd)
    if key not in _managers:
        mgr = McpSessionManager(cwd)
        _managers[key] = mgr
        if connect:
            mgr.connect_all()
    elif connect and not _managers[key]._clients and load_mcp_config(cwd):
        _managers[key].connect_all()
    return _managers[key]


def close_mcp_manager(cwd: str) -> None:
    """Close and drop the cached session manager for a workspace, if any.

    Args:
        cwd: The workspace root whose manager should be closed and evicted.
    """
    key = str(cwd)
    mgr = _managers.pop(key, None)
    if mgr:
        mgr.close()
