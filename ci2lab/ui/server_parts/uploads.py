"""Upload validation, storage and prompt preparation for UI attachments."""

from __future__ import annotations

import base64
import binascii
import os
import re
import uuid
from pathlib import Path
from typing import Any

from ci2lab.harness.tools.filesystem import SUPPORTED_DOCUMENT_SUFFIXES
from ci2lab.harness.tools.secret_files import is_sensitive_path
from ci2lab.ui.server_parts.serializers import format_upload_size

UPLOAD_DIR_NAME = "ci2lab_uploads"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SUPPORTED_UPLOAD_SUFFIXES = {
    ".csv",
    ".css",
    ".docx",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".log",
    ".md",
    ".pdf",
    ".pptx",
    ".py",
    ".rst",
    ".rtf",
    ".text",
    ".toml",
    ".ts",
    ".tsv",
    ".txt",
    ".xml",
    ".xlsx",
    ".yaml",
    ".yml",
}
DOCUMENT_UPLOAD_SUFFIXES = SUPPORTED_DOCUMENT_SUFFIXES | {".rtf"}
MAX_EXTRACTED_RUBRIC_CHARS = 50_000


def upload_file(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and store a base64-encoded attachment in the workspace upload dir.

    Enforces the supported suffix list, decodes and size-checks the content, and
    rejects names that look sensitive before writing the file.

    Args:
        state: The UI server state (provides the runtime workspace).
        payload: Upload payload with ``"name"`` and ``"content_base64"`` keys,
            and an optional ``"workspace"`` override.

    Returns:
        ``{"ok": True, "file": ...}`` on success, otherwise
        ``{"ok": False, "error": ...}`` with a user-facing message.
    """
    workspace = str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    name = str(payload.get("name") or "").strip()
    encoded = str(payload.get("content_base64") or "").strip()
    if not name:
        return {"ok": False, "error": "The file name is missing."}
    if not encoded:
        return {"ok": False, "error": "The file content is missing."}

    safe_name = safe_upload_name(name)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_UPLOAD_SUFFIXES))
        return {
            "ok": False,
            "error": f"Unsupported format. Use one of these: {allowed}",
        }

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

    base = Path(workspace or os.getcwd()).resolve()
    upload_dir = base / UPLOAD_DIR_NAME
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = unique_upload_path(upload_dir, safe_name)
    if is_sensitive_path(target):
        return {
            "ok": False,
            "error": "Names that look like they contain secrets, tokens or credentials are not allowed.",
        }

    target.write_bytes(raw)
    rel_path = target.relative_to(base).as_posix()
    return {
        "ok": True,
        "file": {
            "name": target.name,
            "path": rel_path,
            "size": len(raw),
            "size_label": format_upload_size(len(raw)),
        },
    }


def extract_rubric_pdf(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Temporarily store a rubric PDF and return its extracted text.

    The normal browser text reader cannot decode PDF bytes. This endpoint reuses
    the guarded upload path and the same local document extractor used by chat,
    then removes the temporary upload because the extracted rubric is persisted
    in the researcher profile.
    """
    name = str(payload.get("name") or "").strip()
    if Path(name).suffix.lower() != ".pdf":
        return {"ok": False, "error": "Only PDF files can use rubric extraction."}

    result = upload_file(state, payload)
    if not result.get("ok"):
        return result

    workspace = Path(
        str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    ).resolve()
    file_info = result["file"]
    relative_path = str(file_info["path"])
    target = (workspace / relative_path).resolve()
    upload_root = (workspace / UPLOAD_DIR_NAME).resolve()
    try:
        content = _read_document(str(workspace), relative_path)
    finally:
        if target.parent == upload_root:
            target.unlink(missing_ok=True)

    if content.startswith("Error:"):
        return {
            "ok": False,
            "error": (
                "Could not extract text from the rubric PDF. "
                "Use a text-based PDF or upload the rubric as Markdown or text."
            ),
        }
    content = content.strip()
    if not content:
        return {
            "ok": False,
            "error": "The rubric PDF did not contain extractable text.",
        }
    return {
        "ok": True,
        "rubric": {
            "name": Path(name).name[:200] or "rubric.pdf",
            "content": content[:MAX_EXTRACTED_RUBRIC_CHARS],
        },
    }


def normalize_attachments(raw: Any) -> list[dict[str, str]]:
    """Coerce a raw attachments value into at most five ``{name, path}`` dicts.

    Non-list inputs and malformed entries are ignored; a missing name falls back
    to the path's file name.
    """
    if not isinstance(raw, list):
        return []
    attachments: list[dict[str, str]] = []
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        name = str(item.get("name") or Path(path).name).strip() or Path(path).name
        if path:
            attachments.append({"name": name, "path": path})
    return attachments


def prompt_with_uploaded_files(
    prompt: str,
    workspace: str,
    attachments: list[dict[str, str]],
) -> str:
    """Append already-read attachment contents to a prompt.

    Each attachment is read locally (rejecting paths outside the upload dir),
    and its extracted text — or an error explanation — is added as a block so
    the model can answer without claiming it cannot access the files.

    Args:
        prompt: The user's original prompt.
        workspace: Workspace directory the attachments live under.
        attachments: Normalised ``{name, path}`` attachment entries.

    Returns:
        The prompt unchanged when there are no attachments, otherwise the prompt
        with the rendered attachment content appended.
    """
    if not attachments:
        return prompt

    blocks: list[str] = []
    for file in attachments:
        path = file["path"]
        if not is_upload_path(path):
            blocks.append(
                f"### {file['name']}\n"
                f"Error: attachment rejected because it is not in `{UPLOAD_DIR_NAME}/`."
            )
            continue
        content = _read_document(workspace, path)
        # Spanish prefix kept on purpose: it matches the value returned by
        # read_document (ci2lab.harness.tools, out of scope and still Spanish).
        if content.startswith("Error: unsupported format"):
            content = _read_file(workspace, path)
        if content.startswith("Error:"):
            blocks.append(
                f"### {file['name']}\n"
                f"Local path: {path}\n"
                f"Could not read the attached file: {content}\n"
                "Explain this problem to the user and ask them to install the dependencies "
                "or upload a PDF with extractable text."
            )
            continue
        blocks.append(
            f"### {file['name']}\nLocal path: {path}\nContent read with read_document:\n{content}"
        )

    return (
        f"{prompt}\n\n"
        "Attached files already read locally by Ci2Lab with read_document. "
        "Answer using the following content; do not say that you cannot access the files.\n\n"
        + "\n\n".join(blocks)
    )


def is_upload_path(path: str) -> bool:
    """Return whether ``path`` lies within the upload directory."""
    normalized = path.replace("\\", "/").lstrip("/")
    return normalized == UPLOAD_DIR_NAME or normalized.startswith(f"{UPLOAD_DIR_NAME}/")


def safe_upload_name(name: str) -> str:
    """Sanitise an uploaded file name into a safe, lowercased ``stem+suffix``.

    Strips directory components and null bytes, length-bounds the stem and
    suffix, and replaces disallowed characters, always yielding a non-empty name.
    """
    raw = Path(name).name.strip().replace("\x00", "")
    stem = Path(raw).stem[:90] or "file"
    suffix = Path(raw).suffix[:16]
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._-") or "file"
    safe_suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix)
    return f"{safe_stem}{safe_suffix}".lower()


def unique_upload_path(upload_dir: Path, safe_name: str) -> Path:
    """Return a non-colliding path for ``safe_name`` within ``upload_dir``.

    Appends ``-2``, ``-3``, ... before the suffix until a free name is found,
    falling back to a random suffix after many collisions.
    """
    candidate = upload_dir / safe_name
    if not candidate.exists():
        return candidate
    path = Path(safe_name)
    stem = path.stem or "file"
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = upload_dir / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return upload_dir / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"


def _read_document(workspace: str, path: str) -> str:
    """Read a document via the server facade (extracting text where supported)."""
    from ci2lab.ui import server as facade

    return facade.read_document(workspace, path)


def _read_file(workspace: str, path: str) -> str:
    """Read a raw file's text via the server facade."""
    from ci2lab.ui import server as facade

    return facade.read_file(workspace, path)
