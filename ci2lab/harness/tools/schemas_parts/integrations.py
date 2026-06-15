"""Tool schemas for integrations tools."""

from __future__ import annotations

from typing import Any

INTEGRATIONS_SCHEMAS: list[dict[str, Any]] = [
    {
            "type": "function",
            "function": {
                "name": "web_fetch",
                "description": (
                    "Fetch a public http(s) URL and return text (HTML is stripped). "
                    "Use for docs or reference pages, not for secrets."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {
                            "type": "integer",
                            "description": "Max characters to return (default 80000)",
                        },
                    },
                    "required": ["url"],
                },
            },
        },
    {
            "type": "function",
            "function": {
                "name": "git_status",
                "description": "Show short git status for the workspace or a path inside it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path relative to workspace (default .)",
                        },
                    },
                    "required": [],
                },
            },
        },
    {
            "type": "function",
            "function": {
                "name": "git_diff",
                "description": "Show git diff for the workspace or a specific file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "staged": {
                            "type": "boolean",
                            "description": "If true, show staged changes only",
                        },
                    },
                    "required": [],
                },
            },
        },
    {
            "type": "function",
            "function": {
                "name": "skill",
                "description": (
                    "Load a workspace skill workflow by name. Returns instructions to follow "
                    "using the listed tools. Use when a skill in the catalog matches the task."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "Skill name from the Skills catalog",
                        },
                        "args": {
                            "type": "string",
                            "description": "Optional free-text arguments for the skill",
                        },
                    },
                    "required": ["skill_name"],
                },
            },
        },
    {
            "type": "function",
            "function": {
                "name": "mcp_call",
                "description": (
                    "Call a tool on a connected MCP server by server name and tool name. "
                    "Prefer dedicated mcp__* tools when listed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {"type": "string"},
                        "tool": {"type": "string"},
                        "arguments": {
                            "type": "object",
                            "description": "Tool arguments object",
                        },
                    },
                    "required": ["server", "tool"],
                },
            },
        },
]
