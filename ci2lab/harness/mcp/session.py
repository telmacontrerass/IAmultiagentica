"""MCP session manager: connect servers and expose tools to the harness."""

from __future__ import annotations

import json
import re
from typing import Any

from ci2lab.harness.mcp.client import McpClient, McpTool
from ci2lab.harness.mcp.config import McpServerConfig, load_mcp_config


def mcp_tool_id(server: str, tool: str) -> str:
    safe_server = re.sub(r"[^a-zA-Z0-9_]", "_", server)
    safe_tool = re.sub(r"[^a-zA-Z0-9_]", "_", tool)
    return f"mcp__{safe_server}__{safe_tool}"


def parse_mcp_tool_id(tool_id: str) -> tuple[str, str] | None:
    if not tool_id.startswith("mcp__"):
        return None
    parts = tool_id.split("__", 2)
    if len(parts) != 3:
        return None
    return parts[1], parts[2]


class McpSessionManager:
    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self._clients: dict[str, McpClient] = {}
        self._tools: list[McpTool] = []
        self._tool_index: dict[str, tuple[str, str]] = {}
        self._errors: list[str] = []

    @property
    def tools(self) -> list[McpTool]:
        return list(self._tools)

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def connect_all(self) -> None:
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
            except Exception as exc:  # noqa: BLE001
                self._errors.append(f"{cfg.name}: {exc}")
                client.close()

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()
        self._tools.clear()
        self._tool_index.clear()

    def _client_for_server(self, server: str) -> McpClient | None:
        if server in self._clients:
            return self._clients[server]
        for name, client in self._clients.items():
            if re.sub(r"[^a-zA-Z0-9_]", "_", name) == server:
                return client
        return None

    def call(self, server: str, tool: str, arguments: dict[str, Any]) -> str:
        client = self._client_for_server(server)
        if client is None:
            return f"Error: MCP server `{server}` is not connected"
        try:
            return client.call_tool(tool, arguments)
        except Exception as exc:  # noqa: BLE001
            return f"Error: MCP call failed: {exc}"

    def call_by_id(self, tool_id: str, arguments: dict[str, Any]) -> str:
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
        for t in client.tools:
            if mcp_tool_id(client.server_name, t.name) == f"mcp__{client.server_name}__{sanitized}":
                return t.name
            if re.sub(r"[^a-zA-Z0-9_]", "_", t.name) == sanitized:
                return t.name
        return None

    def build_function_schemas(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for tool in self._tools:
            tid = mcp_tool_id(tool.server, tool.name)
            schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
            properties = schema.get("properties") or {}
            required = schema.get("required") or []
            schemas.append({
                "type": "function",
                "function": {
                    "name": tid,
                    "description": (
                        f"[MCP:{tool.server}] {tool.description or tool.name}"
                    )[:500],
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return schemas

    def format_status(self) -> str:
        if not self._tools and not self._errors:
            return ""
        lines = ["## MCP servers"]
        if self._clients:
            lines.append(
                "Connected: " + ", ".join(sorted(self._clients.keys()))
            )
        for tool in self._tools:
            lines.append(f"- `{mcp_tool_id(tool.server, tool.name)}`: {tool.name}")
        for err in self._errors:
            lines.append(f"- (failed) {err}")
        return "\n".join(lines)


# Per-run cache keyed by cwd
_managers: dict[str, McpSessionManager] = {}


def get_mcp_manager(cwd: str, *, connect: bool = True) -> McpSessionManager:
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
    key = str(cwd)
    mgr = _managers.pop(key, None)
    if mgr:
        mgr.close()
