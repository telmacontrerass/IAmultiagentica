"""Persistence of agent sessions in ~/.ci2lab/sessions/."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sessions_dir() -> Path:
    path = Path.home() / ".ci2lab" / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def save_session(
    session_id: str,
    *,
    messages: list[dict[str, Any]],
    model_tag: str,
    cwd: str,
    token_usage: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> Path:
    payload = {
        "id": session_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model_tag": model_tag,
        "cwd": cwd,
        "messages": normalize_messages_for_storage(messages),
    }
    if token_usage is not None:
        payload["token_usage"] = token_usage
    if project_id:
        payload["project_id"] = project_id
    path = sessions_dir() / f"{session_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_session(session_id: str) -> dict[str, Any] | None:
    path = sessions_dir() / f"{session_id}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = data.get("messages")
    if isinstance(messages, list):
        data["messages"] = normalize_messages_for_storage(messages)
    return data


def delete_session(session_id: str) -> bool:
    path = sessions_dir() / f"{session_id}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True


def is_delete_session_request(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized in {"/delete", "/delete-session", "/forget"}:
        return True
    delete_words = ("delete", "remove", "erase", "forget")
    saved_words = (
        "saved",
        "save",
        "session",
        "conversation",
        "history",
    )
    return any(word in normalized for word in delete_words) and any(
        word in normalized for word in saved_words
    )


def normalize_messages_for_storage(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep persisted histories accepted by OpenAI-compatible backends."""
    normalized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        item = dict(message)
        if item.get("content") is None:
            item["content"] = ""
        normalized.append(item)
    return normalized


def list_sessions() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(sessions_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            messages = data.get("messages", [])
            rows.append({
                "id": data.get("id", path.stem),
                "title": session_title(messages if isinstance(messages, list) else []),
                "model": data.get("model_tag", "?"),
                "cwd": data.get("cwd", "?"),
                "updated_at": data.get("updated_at", "?"),
                "project_id": data.get("project_id"),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return rows


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

    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return "Conversation"

    stopwords = {
        "a", "an", "and", "are", "can", "do", "for", "how", "i", "is", "it",
        "me", "my", "of", "please", "read", "the", "this", "to", "what",
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
