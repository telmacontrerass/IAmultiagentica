"""Tool schemas for runtime tools."""

from __future__ import annotations

from typing import Any

RUNTIME_SCHEMAS: list[dict[str, Any]] = [
    {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Run a shell command (build, tests, installs, running scripts). Asks for confirmation. Prefer read-only tools for exploring; use bash only when no read-only tool fits.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to run"},
                    },
                    "required": ["command"],
                },
            },
        },
]
