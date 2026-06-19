"""Tool schemas for workflow tools."""

from __future__ import annotations

from typing import Any

WORKFLOW_SCHEMAS: list[dict[str, Any]] = [
    {
            "type": "function",
            "function": {
                "name": "delegate",
                "description": (
                    "Run a self-contained subtask in an isolated subagent that does "
                    "not see this conversation — only your task prompt. Just its final "
                    "result returns to you. Use it to keep heavy work out of your own "
                    "context: broad code exploration/search, or one contained "
                    "implementation step. Write a complete, standalone task (the "
                    "subagent has no other context) and state exactly what to return. "
                    "Do NOT delegate trivial single-tool lookups, and do not delegate "
                    "from inside a delegated subagent."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": (
                                "Complete, standalone instructions for the subagent, "
                                "including what result to return."
                            ),
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["explore", "edit"],
                            "description": (
                                "'explore' = read-only research (default); "
                                "'edit' = may create or modify files."
                            ),
                        },
                    },
                    "required": ["task"],
                },
            },
        },
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
