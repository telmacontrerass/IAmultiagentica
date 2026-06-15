"""Tool schemas for workflow tools."""

from __future__ import annotations

from typing import Any

WORKFLOW_SCHEMAS: list[dict[str, Any]] = [
    {
            "type": "function",
            "function": {
                "name": "todo_write",
                "description": (
                    "Replace the workspace task list (.ci2lab/todos.json) for multi-step work. "
                    "Each item needs content and status (pending, in_progress, completed, cancelled)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "content": {"type": "string"},
                                    "status": {"type": "string"},
                                },
                                "required": ["content"],
                            },
                        },
                    },
                    "required": ["todos"],
                },
            },
        },
    {
            "type": "function",
            "function": {
                "name": "ask_user",
                "description": (
                    "Ask the user a question when you need a decision. "
                    "Blocks until the user answers in the terminal."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional numbered choices",
                        },
                    },
                    "required": ["question"],
                },
            },
        },
]
