"""Load MCP server configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class McpServerConfig:
    """Launch configuration for a single MCP server.

    Attributes:
        name: Logical server name used to key and reference the server.
        command: Executable to spawn for the stdio transport.
        args: Command-line arguments passed to ``command``.
        env: Extra environment variables for the server process.
        cwd: Working directory for the server process, or ``None`` to inherit.
    """

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None


def _config_paths(cwd: str) -> list[Path]:
    """Return the candidate ``mcp.json`` paths, in precedence order.

    Args:
        cwd: The workspace root used to resolve workspace-local config files.

    Returns:
        Workspace config paths first, then the per-user config in the home
        directory.
    """
    root = Path(cwd).resolve()
    return [
        root / ".ci2lab" / "mcp.json",
        root / "mcp.json",
        Path.home() / ".ci2lab" / "mcp.json",
    ]


def _parse_server_entry(name: str, raw: dict[str, Any]) -> McpServerConfig | None:
    """Build an :class:`McpServerConfig` from one raw JSON server entry.

    Coerces ``args`` and ``env`` to their expected shapes and stringifies values.

    Args:
        name: The server's key from the config mapping.
        raw: The raw JSON object describing the server.

    Returns:
        A populated :class:`McpServerConfig`, or ``None`` when the entry has no
        usable ``command``.
    """
    command = raw.get("command")
    if not command or not str(command).strip():
        return None
    args = raw.get("args") or []
    if isinstance(args, str):
        args = [args]
    env = raw.get("env") or {}
    if not isinstance(env, dict):
        env = {}
    env_str = {str(k): str(v) for k, v in env.items()}
    return McpServerConfig(
        name=name,
        command=str(command),
        args=[str(a) for a in args],
        env=env_str,
        cwd=str(raw["cwd"]) if raw.get("cwd") else None,
    )


def load_mcp_config(cwd: str) -> list[McpServerConfig]:
    """Merge MCP configs; workspace files override user entries by server name."""
    merged: dict[str, McpServerConfig] = {}
    for path in reversed(_config_paths(cwd)):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        servers = data.get("mcpServers") or data.get("servers") or data
        if not isinstance(servers, dict):
            continue
        for name, entry in servers.items():
            if not isinstance(entry, dict):
                continue
            parsed = _parse_server_entry(str(name), entry)
            if parsed:
                merged[parsed.name] = parsed
    return list(merged.values())
