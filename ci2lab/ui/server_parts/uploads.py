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


def upload_file(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    workspace = str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    name = str(payload.get("name") or "").strip()
    encoded = str(payload.get("content_base64") or "").strip()
    if not name:
        return {"ok": False, "error": "Falta el nombre del archivo."}
    if not encoded:
        return {"ok": False, "error": "Falta el contenido del archivo."}

    safe_name = safe_upload_name(name)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_UPLOAD_SUFFIXES))
        return {
            "ok": False,
            "error": f"Formato no soportado. Usa uno de estos: {allowed}",
        }

    if "," in encoded and encoded.lower().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "El archivo no llegó con un contenido válido."}

    if len(raw) > MAX_UPLOAD_BYTES:
        return {
            "ok": False,
            "error": f"El archivo supera el límite de {format_upload_size(MAX_UPLOAD_BYTES)}.",
        }

    base = Path(workspace or os.getcwd()).resolve()
    upload_dir = base / UPLOAD_DIR_NAME
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = unique_upload_path(upload_dir, safe_name)
    if is_sensitive_path(target):
        return {
            "ok": False,
            "error": "No se admiten nombres que parezcan contener secretos, tokens o credenciales.",
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


def normalize_attachments(raw: Any) -> list[dict[str, str]]:
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
    if not attachments:
        return prompt

    blocks: list[str] = []
    for file in attachments:
        path = file["path"]
        if not is_upload_path(path):
            blocks.append(
                f"### {file['name']}\n"
                f"Error: archivo adjunto rechazado porque no está en `{UPLOAD_DIR_NAME}/`."
            )
            continue
        content = _read_document(workspace, path)
        if content.startswith("Error: formato no soportado"):
            content = _read_file(workspace, path)
        if content.startswith("Error:"):
            blocks.append(
                f"### {file['name']}\n"
                f"Ruta local: {path}\n"
                f"No se pudo leer el archivo adjunto: {content}\n"
                "Explica este problema al usuario y pide que instale las dependencias "
                "o suba un PDF con texto extraible."
            )
            continue
        blocks.append(
            f"### {file['name']}\n"
            f"Ruta local: {path}\n"
            f"Contenido leído con read_document:\n{content}"
        )

    return (
        f"{prompt}\n\n"
        "Archivos adjuntos ya leídos localmente por Ci2Lab con read_document. "
        "Responde usando el contenido siguiente; no digas que no puedes acceder a los archivos.\n\n"
        + "\n\n".join(blocks)
    )


def is_upload_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("/")
    return normalized == UPLOAD_DIR_NAME or normalized.startswith(f"{UPLOAD_DIR_NAME}/")


def safe_upload_name(name: str) -> str:
    raw = Path(name).name.strip().replace("\x00", "")
    stem = Path(raw).stem[:90] or "archivo"
    suffix = Path(raw).suffix[:16]
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._-") or "archivo"
    safe_suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix)
    return f"{safe_stem}{safe_suffix}".lower()


def unique_upload_path(upload_dir: Path, safe_name: str) -> Path:
    candidate = upload_dir / safe_name
    if not candidate.exists():
        return candidate
    path = Path(safe_name)
    stem = path.stem or "archivo"
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = upload_dir / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return upload_dir / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"


def _read_document(workspace: str, path: str) -> str:
    from ci2lab.ui import server as facade

    return facade.read_document(workspace, path)


def _read_file(workspace: str, path: str) -> str:
    from ci2lab.ui import server as facade

    return facade.read_file(workspace, path)

