"""Login-less researcher profiles for the local web UI.

A researcher profile captures who is doing the review and how they review:
their field(s) of expertise, default target venues, reviewing style, and a
per-lens emphasis. There are no passwords — profiles are a local convenience so
each investigator gets their own papers/projects and so the peer-review flow can
adapt its depth and tone to that reviewer (see ``researcher_prompt``).

Profiles live in a single JSON registry at ``~/.ci2lab/researchers.json`` so the
store stays trivial to back up and inspect.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Emphasis levels accepted for per-lens preferences. Unknown values are dropped.
LENS_LEVELS = frozenset({"low", "medium", "high"})

# The reviewer lenses a profile can express a preference for. These mirror the
# multi-agent paper-review roles (see ci2lab/harness/multiagent/state.py).
LENS_KEYS = (
    "scope",
    "novelty",
    "methodology",
    "field_expert",
    "adversarial",
    "format",
)

MAX_NAME_CHARS = 100
MAX_STYLE_CHARS = 2000
MAX_LIST_ITEMS = 30
MAX_ITEM_CHARS = 200


def researchers_path() -> Path:
    """Return the path to the researcher registry file, creating its parent."""
    root = Path.home() / ".ci2lab"
    root.mkdir(parents=True, exist_ok=True)
    return root / "researchers.json"


def _now() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _load_registry() -> list[dict[str, Any]]:
    """Load the researcher registry, returning an empty list on any failure."""
    path = researchers_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict) and row.get("id")]


def _save_registry(rows: list[dict[str, Any]]) -> None:
    """Persist the full researcher registry to disk as pretty-printed JSON."""
    researchers_path().write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _clean_text(value: Any, *, limit: int) -> str:
    """Normalise whitespace and truncate a text value to ``limit`` characters."""
    return " ".join(str(value or "").split()).strip()[:limit]


def _clean_list(value: Any) -> list[str]:
    """Normalise a string or sequence into a de-duplicated list of clean items.

    Comma-separated strings are split; each item has whitespace collapsed and is
    truncated to :data:`MAX_ITEM_CHARS`. Blanks and duplicates are dropped and
    the result is capped at :data:`MAX_LIST_ITEMS`.
    """
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        items = [str(part).strip() for part in value]
    else:
        return []
    cleaned: list[str] = []
    for item in items:
        item = " ".join(item.split())[:MAX_ITEM_CHARS]
        if item and item not in cleaned:
            cleaned.append(item)
        if len(cleaned) >= MAX_LIST_ITEMS:
            break
    return cleaned


def _clean_lens_preferences(value: Any) -> dict[str, str]:
    """Keep only known lens keys mapped to valid emphasis levels.

    Unknown keys and levels outside :data:`LENS_LEVELS` are dropped.
    """
    if not isinstance(value, dict):
        return {}
    prefs: dict[str, str] = {}
    for key in LENS_KEYS:
        level = str(value.get(key) or "").strip().lower()
        if level in LENS_LEVELS:
            prefs[key] = level
    return prefs


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Sanitise a raw researcher payload into the stored profile field set."""
    return {
        "name": _clean_text(payload.get("name"), limit=MAX_NAME_CHARS),
        "email": _clean_text(payload.get("email"), limit=MAX_ITEM_CHARS),
        "fields": _clean_list(payload.get("fields")),
        "default_venues": _clean_list(payload.get("default_venues")),
        "reviewing_style": _clean_text(payload.get("reviewing_style"), limit=MAX_STYLE_CHARS),
        "lens_preferences": _clean_lens_preferences(payload.get("lens_preferences")),
        "preferred_guidelines": _clean_list(payload.get("preferred_guidelines")),
    }


def create_researcher(payload: dict[str, Any]) -> dict[str, Any]:
    """Create and persist a new researcher profile.

    Args:
        payload: Raw profile fields (name, email, fields, venues, style, etc.).

    Returns:
        ``{"ok": True, "researcher": ...}`` on success, otherwise an error dict
        (a non-empty name is required).
    """
    fields = _normalize_payload(payload or {})
    if not fields["name"]:
        return {"ok": False, "error": "A researcher name is required."}

    now = _now()
    researcher_id = f"rsr_{uuid.uuid4().hex[:12]}"
    record = {"id": researcher_id, **fields, "created_at": now, "updated_at": now}
    rows = _load_registry()
    rows.append(record)
    _save_registry(rows)
    return {"ok": True, "researcher": record}


def get_researcher(researcher_id: str) -> dict[str, Any] | None:
    """Return the researcher profile with ``researcher_id``, or ``None``."""
    researcher_id = str(researcher_id or "").strip()
    if not researcher_id:
        return None
    for row in _load_registry():
        if row.get("id") == researcher_id:
            return row
    return None


def list_researchers() -> list[dict[str, Any]]:
    """Return all researcher profiles sorted case-insensitively by name."""
    rows = _load_registry()
    return sorted(rows, key=lambda item: str(item.get("name", "")).lower())


def update_researcher(researcher_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Replace an existing researcher's fields, preserving ``created_at``.

    Args:
        researcher_id: Identifier of the profile to update.
        payload: Raw replacement fields (a non-empty name is required).

    Returns:
        ``{"ok": True, "researcher": ...}`` on success, otherwise an error dict.
    """
    researcher_id = str(researcher_id or "").strip()
    rows = _load_registry()
    fields = _normalize_payload(payload or {})
    if not fields["name"]:
        return {"ok": False, "error": "A researcher name is required."}
    for index, row in enumerate(rows):
        if row.get("id") == researcher_id:
            updated = {
                "id": researcher_id,
                **fields,
                "created_at": row.get("created_at", _now()),
                "updated_at": _now(),
            }
            rows[index] = updated
            _save_registry(rows)
            return {"ok": True, "researcher": updated}
    return {"ok": False, "error": "Researcher not found."}


def delete_researcher(researcher_id: str) -> dict[str, Any]:
    """Delete the researcher profile with ``researcher_id``.

    Returns:
        ``{"ok": True, "researcher_id": ...}`` on success, otherwise an error
        dict when no matching profile exists.
    """
    researcher_id = str(researcher_id or "").strip()
    rows = _load_registry()
    remaining = [row for row in rows if row.get("id") != researcher_id]
    if len(remaining) == len(rows):
        return {"ok": False, "error": "Researcher not found."}
    _save_registry(remaining)
    return {"ok": True, "researcher_id": researcher_id}


def researcher_context_block(profile: dict[str, Any]) -> str:
    """Render a reviewer profile as a prompt block for the peer-review flow.

    The block tells the reviewer agents to ADAPT depth, emphasis, and tone to
    this researcher's field and style while keeping a rigorous standard review.
    """
    if not profile:
        return ""
    lines: list[str] = []
    name = str(profile.get("name") or "").strip()
    if name:
        lines.append(f"- Reviewer: {name}")
    fields = profile.get("fields") or []
    if fields:
        lines.append(f"- Field(s) of expertise: {', '.join(fields)}")
    venues = profile.get("default_venues") or []
    if venues:
        lines.append(f"- Typical target venues: {', '.join(venues)}")
    style = str(profile.get("reviewing_style") or "").strip()
    if style:
        lines.append(f"- Reviewing style: {style}")
    prefs = profile.get("lens_preferences") or {}
    if prefs:
        rendered = ", ".join(f"{key}={level}" for key, level in prefs.items())
        lines.append(f"- Emphasis by lens (low/medium/high): {rendered}")
    guidelines = profile.get("preferred_guidelines") or []
    if guidelines:
        lines.append(f"- Preferred reporting guidelines/checklists: {', '.join(guidelines)}")
    if not lines:
        return ""
    return (
        "<reviewer_profile>\n"
        "Adapt the review's depth, emphasis, and tone to this reviewer's field "
        "and style, but keep a rigorous, standard peer review. This profile never "
        "licenses inventing content: every claim about the paper still requires a "
        "verbatim quote and anchor.\n" + "\n".join(lines) + "\n</reviewer_profile>"
    )


def researcher_prompt(researcher_id: str, prompt: str) -> str:
    """Append the reviewer-profile block to a prompt when a profile is set."""
    profile = get_researcher(researcher_id) if researcher_id else None
    block = researcher_context_block(profile) if profile else ""
    if not block:
        return prompt
    return f"{prompt}\n\n{block}"
