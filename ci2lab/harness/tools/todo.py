"""Structured task list for multi-step agent work.

`open_todos` is the shared source of truth for "is the plan finished?": the
agent loop uses it to stop the model from ending a turn while steps are still
pending, and the tool result nudges the model toward the next step.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ci2lab.harness.tools.paths import resolve_path

TODO_REL_PATH = ".ci2lab/todos.json"
_VALID_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled"})
# Statuses that still need work; a plan with any of these is not finished.
_OPEN_STATUSES = frozenset({"pending", "in_progress"})


def _todo_path(cwd: str) -> Path:
    return resolve_path(TODO_REL_PATH, cwd)


def _normalize_todo(item: dict[str, Any], index: int) -> dict[str, str]:
    todo_id = str(item.get("id") or index + 1)
    content = str(item.get("content") or "").strip()
    if not content:
        raise ValueError(f"Todo {todo_id} must have non-empty content")
    status = str(item.get("status") or "pending").lower()
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"Todo {todo_id} has invalid status {status!r}; "
            f"use one of: {', '.join(sorted(_VALID_STATUSES))}"
        )
    return {"id": todo_id, "content": content, "status": status}


def todo_write(cwd: str, todos: list[dict[str, Any]]) -> str:
    """Replace the workspace todo list with the given items."""
    if not isinstance(todos, list):
        return "Error: todos must be a list of objects"
    if not todos:
        return "Error: todos must not be empty"

    try:
        normalized = [_normalize_todo(item, i) for i, item in enumerate(todos)]
    except (TypeError, ValueError) as exc:
        return f"Error: {exc}"

    target = _todo_path(cwd)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [f"  [{t['status']}] {t['id']}: {t['content']}" for t in normalized]
    header = f"Updated {target} ({len(normalized)} items):\n" + "\n".join(lines)
    # The plan is a means, not the goal. Point the model at the next concrete
    # action so it does not treat writing/updating the list as the task itself
    # and stop — the failure mode where it never gets past the first step.
    return header + "\n\n" + _next_step_hint(normalized)


def _next_step_hint(todos: list[dict[str, str]]) -> str:
    """One actionable line telling the model what to do right after planning."""
    in_progress = [t for t in todos if t["status"] == "in_progress"]
    pending = [t for t in todos if t["status"] == "pending"]
    nxt = (in_progress + pending)
    if not nxt:
        return (
            "All steps are completed. Do NOT call todo_write again. "
            "Give the user the final result now: a short plain-text summary of "
            "what you did and its outcome."
        )
    step = nxt[0]["content"]
    remaining = len(in_progress) + len(pending)
    return (
        f"Plan saved — this is not progress on the task by itself. Now DO the "
        f"next step yourself, immediately, in this same turn: \"{step}\". "
        f"{remaining} step(s) remain. Keep working step by step, marking each "
        f"completed as a tool result confirms it; do not stop or hand back to "
        f"the user until every step is done or you hit a real blocker."
    )


def _load_todos(cwd: str) -> list[dict[str, str]]:
    """Parse the saved todo list, or [] if there is none / it is unreadable."""
    target = _todo_path(cwd)
    if not target.is_file():
        return []
    try:
        items = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def open_todos(cwd: str) -> list[dict[str, str]]:
    """Return the still-unfinished todos (pending or in_progress), in order."""
    return [
        item
        for item in _load_todos(cwd)
        if str(item.get("status", "pending")).lower() in _OPEN_STATUSES
    ]


def todo_read(cwd: str) -> str:
    """Read current todos (helper for tests)."""
    target = _todo_path(cwd)
    if not target.is_file():
        return "(no todos yet)"
    return target.read_text(encoding="utf-8")
