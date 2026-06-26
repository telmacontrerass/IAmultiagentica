"""OpenAI function schemas for runtime tools.

Defines :data:`RUNTIME_SCHEMAS`, the schemas for tools that execute commands in
the workspace (currently ``bash``). These are aggregated into the full tool set
by :mod:`ci2lab.harness.tools.schemas_parts.builtins`.
"""

from __future__ import annotations

from typing import Any

#: OpenAI-compatible function schemas for runtime/execution tools.
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
