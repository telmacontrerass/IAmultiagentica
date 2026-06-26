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
    {
            "type": "function",
            "function": {
                "name": "calc",
                "description": (
                    "Evaluate an arithmetic expression exactly and return its value. "
                    "Use this to verify any sum, product, or fraction before you write "
                    "it down — do not compute multi-term arithmetic in your head. "
                    "Arithmetic only: numbers and + - * / // % ** with parentheses and "
                    "unary minus, e.g. '8*(-393520) + 9*(-241820) - (-249910)' or "
                    "'298 + 5074630 / (8*58.4 + 9*47.15 + 47*34.9)'. No variables or functions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "Arithmetic expression to evaluate exactly.",
                        },
                    },
                    "required": ["expression"],
                },
            },
        },
]
