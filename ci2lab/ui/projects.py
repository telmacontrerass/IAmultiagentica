"""Persistent, isolated knowledge projects for the local web UI."""

from __future__ import annotations

import base64
import binascii
import re
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ci2lab.harness.tools.filesystem import read_document, read_file
from ci2lab.harness.tools.secret_files import is_sensitive_path
from ci2lab.ui.server_parts.serializers import format_upload_size
from ci2lab.ui.server_parts.uploads import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_UPLOAD_SUFFIXES,
    safe_upload_name,
    unique_upload_path,
)

PROJECT_CONTEXT_CHARS = 24_000
PROJECT_SOURCE_LIMIT = 100

# Optional per-project metadata. Knowledge projects leave these empty; a
# paper-review project ("kind" == "paper_review") uses them to center everything
# on one manuscript and to route/adapt the peer-review flow.
PROJECT_METADATA_COLUMNS: dict[str, str] = {
    "owner_id": "TEXT",
    "kind": "TEXT",
    "paper_title": "TEXT",
    "field": "TEXT",
    "target_venue": "TEXT",
    "article_type": "TEXT",
    "reviewer_profile_id": "TEXT",
    "manuscript_source_id": "TEXT",
    "maturity": "TEXT",
    "review_status": "TEXT",
}

PROJECT_KINDS = frozenset({"knowledge", "paper_review"})


def projects_root() -> Path:
    """Return the root directory for all projects, creating it if needed."""
    root = Path.home() / ".ci2lab" / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _valid_project_id(project_id: str) -> bool:
    """Return whether ``project_id`` matches the allowed identifier pattern."""
    return bool(project_id) and bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{5,63}", project_id))


def project_dir(project_id: str) -> Path | None:
    """Resolve a project's directory, guarding against path traversal.

    Args:
        project_id: The project identifier to resolve.

    Returns:
        The project directory under :func:`projects_root`, or ``None`` if the id
        is invalid or would escape the projects root.
    """
    if not _valid_project_id(project_id):
        return None
    root = projects_root().resolve()
    path = (root / project_id).resolve()
    if path.parent != root:
        return None
    return path


def _connect(path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with row access and foreign keys enabled."""
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def _database(path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a transactional SQLite connection, committing then closing it."""
    connection = _connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _ensure_source_ownership(db: sqlite3.Connection, project_id: str) -> None:
    """Tag legacy rows and make project ownership queryable inside each DB."""
    columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(sources)").fetchall()}
    if "project_id" not in columns:
        db.execute("ALTER TABLE sources ADD COLUMN project_id TEXT")
    db.execute(
        "UPDATE sources SET project_id = ? WHERE project_id IS NULL OR project_id = ''",
        (project_id,),
    )


def _ensure_project_metadata(db: sqlite3.Connection) -> None:
    """Add optional metadata columns to legacy ``project`` tables in place."""
    columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(project)").fetchall()}
    for name, sqltype in PROJECT_METADATA_COLUMNS.items():
        if name not in columns:
            db.execute(f"ALTER TABLE project ADD COLUMN {name} {sqltype}")
    db.execute("UPDATE project SET kind = 'knowledge' WHERE kind IS NULL OR kind = ''")


def _initialize_database(path: Path, *, project_id: str, name: str) -> None:
    """Create the project/sources schema and upsert the project row.

    Args:
        path: Path to the project's SQLite database file.
        project_id: Identifier of the project being initialised.
        name: Display name to store for the project.
    """
    now = datetime.now(UTC).isoformat()
    with _database(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS project (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        db.execute(
            """
            INSERT OR REPLACE INTO project (id, name, created_at, updated_at)
            VALUES (?, ?, COALESCE((SELECT created_at FROM project WHERE id = ?), ?), ?)
            """,
            (project_id, name, project_id, now, now),
        )
        _ensure_source_ownership(db, project_id)
        _ensure_project_metadata(db)


def _clean_meta_value(value: Any) -> str:
    """Normalise whitespace and truncate a metadata value to 300 characters."""
    return " ".join(str(value or "").split()).strip()[:300]


def create_project(
    name: str,
    *,
    owner_id: str | None = None,
    kind: str = "knowledge",
    paper_title: str | None = None,
    field: str | None = None,
    target_venue: str | None = None,
    article_type: str | None = None,
    reviewer_profile_id: str | None = None,
) -> dict[str, Any]:
    """Create a new isolated project and its on-disk database.

    Args:
        name: Display name (1-100 characters after whitespace normalisation).
        owner_id: Optional researcher id that owns the project.
        kind: Project kind; one of :data:`PROJECT_KINDS`.
        paper_title: Optional manuscript title for paper-review projects.
        field: Optional research field metadata.
        target_venue: Optional target publication venue.
        article_type: Optional article-type metadata.
        reviewer_profile_id: Optional default reviewer profile id.

    Returns:
        ``{"ok": True, "project": ...}`` on success, otherwise
        ``{"ok": False, "error": ...}`` with a user-facing message.
    """
    clean_name = " ".join(str(name or "").split()).strip()
    if not clean_name:
        return {"ok": False, "error": "Project name is required."}
    if len(clean_name) > 100:
        return {"ok": False, "error": "Project name must be 100 characters or fewer."}
    kind = (kind or "knowledge").strip().lower()
    if kind not in PROJECT_KINDS:
        return {"ok": False, "error": "Unknown project kind."}

    project_id = f"prj_{uuid.uuid4().hex[:12]}"
    path = projects_root() / project_id
    (path / "sources").mkdir(parents=True)
    _initialize_database(path / "project.sqlite3", project_id=project_id, name=clean_name)
    metadata = {
        "owner_id": owner_id,
        "kind": kind,
        "paper_title": paper_title,
        "field": field,
        "target_venue": target_venue,
        "article_type": article_type,
        "reviewer_profile_id": reviewer_profile_id,
    }
    metadata = {key: value for key, value in metadata.items() if value not in (None, "")}
    if metadata:
        update_project_metadata(project_id, metadata)
    return {"ok": True, "project": get_project(project_id)}


def update_project_metadata(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Update name and/or paper-review metadata on a project."""
    path = project_dir(project_id)
    if path is None or not (path / "project.sqlite3").is_file():
        return {"ok": False, "error": "Project not found."}

    assignments: dict[str, Any] = {}
    if "name" in payload:
        clean_name = " ".join(str(payload.get("name") or "").split()).strip()
        if not clean_name or len(clean_name) > 100:
            return {"ok": False, "error": "Use a project name between 1 and 100 characters."}
        assignments["name"] = clean_name
    for column in PROJECT_METADATA_COLUMNS:
        if column not in payload:
            continue
        value = _clean_meta_value(payload.get(column))
        if column == "kind" and value and value.lower() not in PROJECT_KINDS:
            return {"ok": False, "error": "Unknown project kind."}
        assignments[column] = value.lower() if column == "kind" else value

    if not assignments:
        return {"ok": True, "project": get_project(project_id)}

    now = datetime.now(UTC).isoformat()
    set_clause = ", ".join(f"{column} = ?" for column in assignments)
    values = list(assignments.values())
    with _database(path / "project.sqlite3") as db:
        _ensure_project_metadata(db)
        db.execute(
            f"UPDATE project SET {set_clause}, updated_at = ? WHERE id = ?",
            (*values, now, project_id),
        )
    return {"ok": True, "project": get_project(project_id)}


def get_project(project_id: str) -> dict[str, Any] | None:
    """Return a project's full record including source counts and metadata.

    Args:
        project_id: Identifier of the project to load.

    Returns:
        A dict describing the project (id, name, timestamps, source stats,
        workspace path and metadata columns), or ``None`` when the project does
        not exist or its database cannot be read.
    """
    path = project_dir(project_id)
    if path is None or not (path / "project.sqlite3").is_file():
        return None
    try:
        with _database(path / "project.sqlite3") as db:
            _ensure_project_metadata(db)
            _ensure_source_ownership(db, project_id)
            row = db.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                return None
            source_count = db.execute(
                "SELECT COUNT(*) FROM sources WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
            source_bytes = db.execute(
                "SELECT COALESCE(SUM(size), 0) FROM sources WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
    except sqlite3.Error:
        return None
    keys = set(row.keys())
    project = {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "source_count": int(source_count),
        "source_bytes": int(source_bytes),
        "source_size_label": format_upload_size(int(source_bytes)),
        "workspace": str(path),
    }
    for column in PROJECT_METADATA_COLUMNS:
        project[column] = row[column] if column in keys else None
    project["kind"] = project.get("kind") or "knowledge"
    return project


def list_projects(owner_id: str | None = None) -> list[dict[str, Any]]:
    """List projects, optionally scoped to one researcher.

    When ``owner_id`` is given, return that researcher's projects plus any
    legacy/unassigned project (no owner) so nothing silently disappears in a
    multi-researcher setup that still has no authentication.
    """
    owner_id = (owner_id or "").strip()
    rows = []
    for path in projects_root().iterdir():
        if not path.is_dir():
            continue
        project = get_project(path.name)
        if not project:
            continue
        if owner_id:
            project_owner = (project.get("owner_id") or "").strip()
            if project_owner and project_owner != owner_id:
                continue
        rows.append(project)
    return sorted(rows, key=lambda item: item["updated_at"], reverse=True)


def rename_project(project_id: str, name: str) -> dict[str, Any]:
    """Rename a project, validating the new name length.

    Returns:
        ``{"ok": True, "project": ...}`` on success, otherwise an error dict.
    """
    path = project_dir(project_id)
    clean_name = " ".join(str(name or "").split()).strip()
    if path is None or not (path / "project.sqlite3").is_file():
        return {"ok": False, "error": "Project not found."}
    if not clean_name or len(clean_name) > 100:
        return {"ok": False, "error": "Use a project name between 1 and 100 characters."}
    now = datetime.now(UTC).isoformat()
    with _database(path / "project.sqlite3") as db:
        db.execute(
            "UPDATE project SET name = ?, updated_at = ? WHERE id = ?",
            (clean_name, now, project_id),
        )
    return {"ok": True, "project": get_project(project_id)}


def delete_project(project_id: str) -> dict[str, Any]:
    """Delete a project, its workspace, and any sessions scoped to it.

    Returns:
        ``{"ok": True, "project_id": ...}`` on success, otherwise an error dict.
    """
    path = project_dir(project_id)
    if path is None or not path.is_dir() or get_project(project_id) is None:
        return {"ok": False, "error": "Project not found."}
    # Project conversations are part of the same isolated workspace. Remove
    # them together so no orphaned chat can retain project-only context.
    from ci2lab.harness.session import delete_session, list_sessions, load_session

    for row in list_sessions():
        session_id = str(row.get("id") or "")
        session = load_session(session_id) if session_id else None
        if session and session.get("project_id") == project_id:
            delete_session(session_id)
    shutil.rmtree(path)
    return {"ok": True, "project_id": project_id}


def list_project_sources(project_id: str) -> dict[str, Any]:
    """List a project's indexed source files, newest first.

    Returns:
        ``{"ok": True, "sources": [...]}`` on success, otherwise an error dict.
    """
    path = project_dir(project_id)
    if path is None or not (path / "project.sqlite3").is_file():
        return {"ok": False, "error": "Project not found."}
    with _database(path / "project.sqlite3") as db:
        _ensure_source_ownership(db, project_id)
        rows = db.execute(
            """
            SELECT id, name, relative_path, size, created_at
            FROM sources WHERE project_id = ? ORDER BY created_at DESC
            """,
            (project_id,),
        ).fetchall()
    return {
        "ok": True,
        "sources": [
            {
                "id": row["id"],
                "name": row["name"],
                "path": row["relative_path"],
                "size": row["size"],
                "size_label": format_upload_size(row["size"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }


def add_project_source(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Decode, store and index a base64-encoded source file into a project.

    Validates the name, format, size and sensitivity, writes the file under the
    project's ``sources`` directory, extracts text, and records a source row.

    Args:
        project_id: Identifier of the target project.
        payload: Upload payload with ``"name"`` and ``"content_base64"`` keys.

    Returns:
        ``{"ok": True, "source": ..., "project": ...}`` on success, otherwise
        ``{"ok": False, "error": ...}`` with a user-facing message.
    """
    path = project_dir(project_id)
    if path is None or not (path / "project.sqlite3").is_file():
        return {"ok": False, "error": "Project not found."}

    name = str(payload.get("name") or "").strip()
    encoded = str(payload.get("content_base64") or "").strip()
    if not name or not encoded:
        return {"ok": False, "error": "File name and content are required."}
    safe_name = safe_upload_name(name)
    if Path(safe_name).suffix.lower() not in SUPPORTED_UPLOAD_SUFFIXES:
        return {"ok": False, "error": "Unsupported source format."}
    if "," in encoded and encoded.lower().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "The file did not arrive with valid content."}
    if len(raw) > MAX_UPLOAD_BYTES:
        return {
            "ok": False,
            "error": f"The file exceeds the {format_upload_size(MAX_UPLOAD_BYTES)} limit.",
        }

    with _database(path / "project.sqlite3") as db:
        _ensure_source_ownership(db, project_id)
        count = db.execute(
            "SELECT COUNT(*) FROM sources WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        if count >= PROJECT_SOURCE_LIMIT:
            return {
                "ok": False,
                "error": f"A project can contain up to {PROJECT_SOURCE_LIMIT} sources.",
            }

    target = unique_upload_path(path / "sources", safe_name)
    if is_sensitive_path(target):
        return {"ok": False, "error": "That file name looks sensitive and was rejected."}
    target.write_bytes(raw)
    relative_path = target.relative_to(path).as_posix()
    content = read_document(str(path), relative_path)
    if content.startswith("Error: unsupported format"):
        content = read_file(str(path), relative_path)
    if content.startswith("Error:"):
        target.unlink(missing_ok=True)
        return {"ok": False, "error": f"Could not index the source: {content}"}

    source_id = f"src_{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    with _database(path / "project.sqlite3") as db:
        db.execute(
            """
            INSERT INTO sources (
                id, project_id, name, relative_path, size, content, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                project_id,
                target.name,
                relative_path,
                len(raw),
                content,
                now,
            ),
        )
        db.execute(
            "UPDATE project SET updated_at = ? WHERE id = ?",
            (now, project_id),
        )
    return {
        "ok": True,
        "source": {
            "id": source_id,
            "name": target.name,
            "path": relative_path,
            "size": len(raw),
            "size_label": format_upload_size(len(raw)),
            "created_at": now,
        },
        "project": get_project(project_id),
    }


def delete_project_source(project_id: str, source_id: str) -> dict[str, Any]:
    """Remove a source from a project, deleting its row and stored file.

    Returns:
        ``{"ok": True, "source_id": ..., "project": ...}`` on success, otherwise
        an error dict.
    """
    path = project_dir(project_id)
    if path is None or not (path / "project.sqlite3").is_file():
        return {"ok": False, "error": "Project not found."}
    with _database(path / "project.sqlite3") as db:
        _ensure_source_ownership(db, project_id)
        row = db.execute(
            """
            SELECT relative_path FROM sources
            WHERE id = ? AND project_id = ?
            """,
            (source_id, project_id),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "Source not found."}
        db.execute(
            "DELETE FROM sources WHERE id = ? AND project_id = ?",
            (source_id, project_id),
        )
        db.execute(
            "UPDATE project SET updated_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), project_id),
        )
    target = (path / row["relative_path"]).resolve()
    if target.is_relative_to(path.resolve()):
        target.unlink(missing_ok=True)
    return {"ok": True, "source_id": source_id, "project": get_project(project_id)}


def _terms(text: str) -> set[str]:
    """Tokenise text into a set of lowercased terms, dropping common stopwords."""
    return {
        token
        for token in re.findall(r"[\wÀ-ÿ]{3,}", text.lower())
        if token
        not in {
            "para",
            "como",
            "este",
            "esta",
            "that",
            "with",
            "from",
            "have",
            "sobre",
            "entre",
            "the",
            "and",
            "una",
            "uno",
            "unos",
            "unas",
        }
    }


def _chunks(text: str, size: int = 3500, overlap: int = 350) -> list[str]:
    """Split text into overlapping character windows for retrieval.

    Args:
        text: Source text to chunk.
        size: Maximum characters per chunk.
        overlap: Number of trailing characters repeated at the start of the next
            chunk to preserve context across boundaries.

    Returns:
        The list of chunks (empty when the text is blank).
    """
    clean = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not clean:
        return []
    chunks = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + size)
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = max(start + 1, end - overlap)
    return chunks


def project_context(project_id: str, query: str) -> str:
    """Return relevant excerpts from one project's private source database."""
    path = project_dir(project_id)
    if path is None or not (path / "project.sqlite3").is_file():
        return ""
    query_terms = _terms(query)
    candidates: list[tuple[int, str, str]] = []
    with _database(path / "project.sqlite3") as db:
        _ensure_source_ownership(db, project_id)
        rows = db.execute(
            "SELECT name, content FROM sources WHERE project_id = ?",
            (project_id,),
        ).fetchall()
    for row in rows:
        for chunk in _chunks(row["content"]):
            overlap = len(query_terms & _terms(chunk))
            candidates.append((overlap, row["name"], chunk))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], len(item[2])), reverse=True)
    selected = candidates[:6]
    if query_terms and any(score > 0 for score, _, _ in candidates):
        selected = [item for item in candidates if item[0] > 0][:6]

    blocks = []
    used = 0
    for _, name, chunk in selected:
        block = f"### Source: {name}\n{chunk.strip()}"
        if used + len(block) > PROJECT_CONTEXT_CHARS:
            remaining = PROJECT_CONTEXT_CHARS - used
            if remaining > 300:
                blocks.append(block[:remaining])
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def project_manuscript_text(project_id: str) -> tuple[str, str]:
    """Return ``(text, source_name)`` for a paper-review project's manuscript.

    Grounding must verify quotes against the manuscript only, so we pick a single
    source: the one named in ``manuscript_source_id`` if set, otherwise the
    largest source (the full paper, not a guidelines snippet). Returns empty
    strings when the project has no readable source.
    """
    path = project_dir(project_id)
    if path is None or not (path / "project.sqlite3").is_file():
        return "", ""
    project = get_project(project_id)
    chosen_id = (project or {}).get("manuscript_source_id") or ""
    with _database(path / "project.sqlite3") as db:
        _ensure_source_ownership(db, project_id)
        if chosen_id:
            row = db.execute(
                "SELECT name, content FROM sources WHERE id = ? AND project_id = ?",
                (chosen_id, project_id),
            ).fetchone()
            if row is not None:
                return str(row["content"] or ""), str(row["name"] or "")
        row = db.execute(
            """
            SELECT name, content FROM sources
            WHERE project_id = ? ORDER BY size DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    if row is None:
        return "", ""
    return str(row["content"] or ""), str(row["name"] or "")


def project_prompt(project_id: str, prompt: str) -> str:
    """Wrap a user prompt with the project's name and relevant source excerpts.

    Args:
        project_id: Identifier of the active project.
        prompt: The user's original prompt.

    Returns:
        The prompt unchanged when the project is missing; otherwise the prompt
        augmented with project framing and (when available) a
        ``<project_sources>`` context block.
    """
    project = get_project(project_id)
    if project is None:
        return prompt
    context = project_context(project_id, prompt)
    if not context:
        return (
            f"{prompt}\n\n"
            f"You are working inside the project “{project['name']}”. "
            "This project currently has no readable reference sources. Say so if "
            "the request depends on project material."
        )
    return (
        f"{prompt}\n\n"
        f"You are working inside the isolated project “{project['name']}”. "
        "Use the project sources below as the primary reference. Distinguish facts "
        "found in the sources from your general knowledge, and mention the source "
        "file names when they support the answer.\n\n"
        f"<project_sources>\n{context}\n</project_sources>"
    )
