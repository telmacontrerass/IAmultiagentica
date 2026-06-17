"""Small serializers and formatters for UI API responses."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ci2lab.harness.session import delete_session, list_sessions, load_session


def disk_payload(workspace: str) -> dict[str, Any]:
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
    return round(float(value) / (1024**3), 2)


def format_upload_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def sessions_payload() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in list_sessions():
        session_id = str(row.get("id") or "")
        data = load_session(session_id) if session_id else None
        enriched = dict(row)
        enriched["internal_tag"] = session_id
        enriched["title"] = session_title(data.get("messages", []) if data else [])
        rows.append(enriched)
    return rows


def session_payload(session_id: str) -> tuple[dict[str, Any], int]:
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
        },
    }, 200


def delete_session_payload(session_id: str) -> tuple[dict[str, Any], int]:
    if not session_id or not all(ch.isalnum() or ch in "-_" for ch in session_id):
        return {"ok": False, "error": "Invalid session."}, 400
    deleted = delete_session(session_id)
    if not deleted:
        return {"ok": False, "error": "Session not found."}, 404
    return {"ok": True, "session_id": session_id}, 200


def session_title(messages: list[dict[str, Any]]) -> str:
    text = ""
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = message_text(message.get("content")).strip()
        if text:
            break
    if not text:
        return "Conversation"

    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+", text)
    if not words:
        return "Conversation"

    stopwords = {
        "a", "al", "and", "are", "can", "como", "con", "de", "del", "do", "el",
        "en", "es", "este", "for", "haz", "how", "i", "is", "it", "la", "las",
        "le", "lo", "los", "me", "mi", "of", "para", "please", "por", "puedes",
        "que", "read", "se", "sobre", "the", "this", "to", "un", "una", "what",
        "where", "you",
    }
    keywords = [word for word in words if word.lower() not in stopwords]
    chosen = (keywords or words)[:4]
    title = " ".join(chosen).strip()
    if len(title) > 48:
        title = f"{title[:45].rstrip()}..."
    return title[:1].upper() + title[1:] if title else "Conversation"


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def public_pull_task(task: dict[str, Any]) -> dict[str, Any]:
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
    base = Path(runs_dir)
    if not base.is_dir():
        return []
    rows = []
    for path in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        if path.is_dir():
            rows.append({
                "name": path.name,
                "path": str(path),
                "modified": path.stat().st_mtime,
            })
    return rows


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
