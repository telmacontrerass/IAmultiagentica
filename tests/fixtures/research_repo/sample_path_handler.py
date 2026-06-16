from __future__ import annotations

from pathlib import Path


def normalize_user_path(raw: str) -> str:
    candidate = Path(raw).expanduser()
    text = candidate.as_posix()
    if text.startswith("../"):
        raise ValueError("parent traversal is not allowed")
    return text


def cache_ttl_seconds() -> int:
    return 300


def retry_attempts() -> int:
    return 5
