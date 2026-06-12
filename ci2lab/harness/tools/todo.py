"""Structured task list for multi-step agent work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ci2lab.harness.tools.paths import resolve_path

TODO_REL_PATH = ".ci2lab/todos.json"
_VALID_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled"})


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
    return f"Updated {target} ({len(normalized)} items):\n" + "\n".join(lines)


def todo_read(cwd: str) -> str:
    """Read current todos (helper for tests)."""
    target = _todo_path(cwd)
    if not target.is_file():
        return "(no todos yet)"
    return target.read_text(encoding="utf-8")
