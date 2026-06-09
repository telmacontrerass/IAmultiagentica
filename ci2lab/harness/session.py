"""Persistencia de sesiones de agente en ~/.ci2lab/sessions/."""

from __future__ import annotations

import json
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
) -> Path:
    payload = {
        "id": session_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model_tag": model_tag,
        "cwd": cwd,
        "messages": messages,
    }
    path = sessions_dir() / f"{session_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_session(session_id: str) -> dict[str, Any] | None:
    path = sessions_dir() / f"{session_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_sessions() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(sessions_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.append({
                "id": data.get("id", path.stem),
                "model": data.get("model_tag", "?"),
                "cwd": data.get("cwd", "?"),
                "updated_at": data.get("updated_at", "?"),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return rows
