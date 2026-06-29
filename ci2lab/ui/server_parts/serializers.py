"""Small serializers and formatters for UI API responses."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ci2lab.harness.session import (
    delete_session,
    list_sessions,
    load_session,
    message_text,
    session_title,
)


def disk_payload(workspace: str) -> dict[str, Any]:
    """Return disk-usage stats (in GB and percentages) for a workspace path.

    Falls back to the current working directory when ``workspace`` does not
    exist.
    """
    path = Path(workspace)
    if not path.exists():
        path = Path.cwd()
    usage = shutil.disk_usage(path)
    total_gb = bytes_to_gb(usage.total)
    free_gb = bytes_to_gb(usage.free)
    used_gb = bytes_to_gb(usage.used)
    used_percent = round((usage.used / usage.total * 100), 1) if usage.total else 0.0
    return {
        "path": str(path),
        "total_gb": total_gb,
        "used_gb": used_gb,
        "free_gb": free_gb,
        "used_percent": used_percent,
        "free_percent": round(100 - used_percent, 1),
    }


def bytes_to_gb(value: int | float) -> float:
    """Convert a byte count to gibibytes, rounded to two decimals."""
    return round(float(value) / (1024**3), 2)


def format_upload_size(num_bytes: int) -> str:
    """Format a byte count as a human-readable ``B``/``KB``/``MB`` string."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def sessions_payload() -> list[dict[str, Any]]:
    """Return all sessions, each tagged with its id as ``internal_tag``."""
    rows: list[dict[str, Any]] = []
    for row in list_sessions():
        session_id = str(row.get("id") or "")
        enriched = dict(row)
        enriched["internal_tag"] = session_id
        rows.append(enriched)
    return rows


def session_payload(session_id: str) -> tuple[dict[str, Any], int]:
    """Load one session as a UI payload with its visible messages.

    Args:
        session_id: Identifier of the session to load.

    Returns:
        A ``(payload, http_status)`` tuple: 400 for an invalid id, 404 when not
        found, and 200 with the serialised session otherwise.
    """
    if not session_id or not all(ch.isalnum() or ch in "-_" for ch in session_id):
        return {"ok": False, "error": "Invalid session."}, 400
    data = load_session(session_id)
    if not data:
        return {"ok": False, "error": "Session not found."}, 404

    messages = []
    for message in data.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = message_text(message.get("content"))
        if role in {"user", "assistant", "system"} and content:
            messages.append({"role": role, "content": content})
    return {
        "ok": True,
        "session": {
            "id": data.get("id", session_id),
            "internal_tag": data.get("id", session_id),
            "title": session_title(data.get("messages", [])),
            "model": data.get("model_tag", "?"),
            "cwd": data.get("cwd", "?"),
            "updated_at": data.get("updated_at", "?"),
            "messages": messages,
            "token_usage": data.get("token_usage") or {},
            "project_id": data.get("project_id"),
        },
    }, 200


def delete_session_payload(session_id: str) -> tuple[dict[str, Any], int]:
    """Delete a session and return a ``(payload, http_status)`` UI response.

    Returns 400 for an invalid id, 404 when not found, and 200 on success.
    """
    if not session_id or not all(ch.isalnum() or ch in "-_" for ch in session_id):
        return {"ok": False, "error": "Invalid session."}, 400
    deleted = delete_session(session_id)
    if not deleted:
        return {"ok": False, "error": "Session not found."}, 404
    return {"ok": True, "session_id": session_id}, 200


def public_pull_task(task: dict[str, Any]) -> dict[str, Any]:
    """Project an internal pull-task dict to its public, client-safe fields."""
    return {
        "id": task["id"],
        "tag": task["tag"],
        "status": task["status"],
        "completed": task["completed"],
        "total": task["total"],
        "percent": task["percent"],
        "done": task["done"],
        "ok": task["ok"],
        "error": task["error"],
    }


def public_delete_task(task: dict[str, Any]) -> dict[str, Any]:
    """Project an internal delete-task dict to its public, client-safe fields."""
    return {
        "id": task["id"],
        "tag": task["tag"],
        "status": task["status"],
        "percent": task["percent"],
        "done": task["done"],
        "ok": task["ok"],
        "error": task["error"],
    }


def list_runs(runs_dir: str) -> list[dict[str, Any]]:
    """Return up to the 20 most recent run directories under ``runs_dir``.

    Each entry carries the run ``name``, absolute ``path`` and ``modified``
    timestamp; the list is empty when the directory does not exist.
    """
    base = Path(runs_dir)
    if not base.is_dir():
        return []
    rows = []
    for path in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        if path.is_dir():
            rows.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "modified": path.stat().st_mtime,
                }
            )
    return rows


def safe_int(value: Any) -> int:
    """Coerce a value to ``int``, returning ``0`` on ``None`` or invalid input."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
