"""Document-request detection and deterministic read helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ci2lab.harness.document_answer import maybe_answer_document_request
from ci2lab.harness.types import ToolCall, ToolResult

DOCUMENT_EXTENSIONS = (
    "pdf", "docx", "pptx", "xlsx", "csv", "tsv", "md", "rst", "txt",
    "text", "json", "yaml", "yml",
)
_DOCUMENT_PATH_RE = re.compile(
    rf"(?P<path>[^\s`\"']+\.({'|'.join(DOCUMENT_EXTENSIONS)}))\b",
    re.IGNORECASE,
)
_DOCUMENT_TYPE_EXTENSIONS = {
    "pdf": {".pdf"},
    "word": {".docx"},
    "docx": {".docx"},
    "excel": {".xlsx", ".csv", ".tsv"},
    "xlsx": {".xlsx"},
    "csv": {".csv"},
    "powerpoint": {".pptx"},
    "presentacion": {".pptx"},
    "presentación": {".pptx"},
    "pptx": {".pptx"},
}
_DOCUMENT_REQUEST_CUES = frozenset(
    {"archivo", "documento", "fichero", "pdf", "word", "docx", "excel",
     "xlsx", "csv", "powerpoint", "presentacion", "presentación", "pptx"}
)
_SKIPPED_DOCUMENT_DIRS = frozenset(
    {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
     "node_modules", "runs"}
)


def forced_document_read_tool_call(user_prompt: str, cwd: str) -> ToolCall | None:
    if not looks_like_document_read_request(user_prompt):
        return None
    document_path = document_path_from_prompt(user_prompt, cwd)
    if not document_path:
        return None
    return ToolCall(
        name="read_document",
        arguments={"path": document_path},
        call_id="auto_document_read",
    )


def document_request_missing_message(user_prompt: str, cwd: str) -> str | None:
    if not looks_like_document_read_request(user_prompt):
        return None
    if document_path_from_prompt(user_prompt, cwd):
        return None
    candidates = document_candidates(cwd, requested_document_extensions(user_prompt))
    if not candidates:
        return (
            "No encuentro un documento claro para leer. Escribe el nombre del archivo "
            "con extension, por ejemplo: `resume prueba.pdf`."
        )
    shown = [f"- {relative_document_path(path, cwd)}" for path in candidates[:8]]
    more = "" if len(candidates) <= 8 else f"\n... y {len(candidates) - 8} mas"
    return (
        "No sé con seguridad qué documento quieres leer. Prueba con uno de estos:\n\n"
        + "\n".join(shown)
        + more
    )


def document_direct_answer(
    results: list[ToolResult], original_user_prompt: str
) -> str | None:
    outputs = [
        result.content
        for result in results
        if result.tool_name in {"read_file", "read_document"}
        and not result.is_error
        and ("Texto extraido:" in result.content or "[PDF page " in result.content)
    ]
    return maybe_answer_document_request(original_user_prompt, outputs)


def document_path_from_prompt(user_prompt: str, cwd: str) -> str | None:
    match = _DOCUMENT_PATH_RE.search(user_prompt)
    if match:
        return match.group("path")
    candidates = document_candidates(cwd, requested_document_extensions(user_prompt))
    if not candidates:
        return None
    prompt_tokens = set(word_tokens(user_prompt))
    scored: list[tuple[int, str]] = []
    for candidate in candidates:
        stem_tokens = set(word_tokens(candidate.stem))
        score = len(prompt_tokens & stem_tokens)
        if candidate.stem.lower() in user_prompt.lower():
            score += 3
        if score:
            scored.append((score, relative_document_path(candidate, cwd)))
    if scored:
        scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
        if len(scored) == 1 or scored[0][0] > scored[1][0]:
            return scored[0][1]
    requested = requested_document_extensions(user_prompt)
    if requested and len(candidates) == 1:
        return relative_document_path(candidates[0], cwd)
    return None


def requested_document_extensions(user_prompt: str) -> set[str] | None:
    text = user_prompt.lower()
    requested: set[str] = set()
    for marker, extensions in _DOCUMENT_TYPE_EXTENSIONS.items():
        if marker in text:
            requested.update(extensions)
    return requested or None


def document_candidates(cwd: str, extensions: set[str] | None = None) -> list[Path]:
    root = Path(cwd).resolve()
    supported = {f".{ext}" for ext in DOCUMENT_EXTENSIONS}
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if any(part in _SKIPPED_DOCUMENT_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in supported:
            continue
        if extensions and path.suffix.lower() not in extensions:
            continue
        candidates.append(path)
        if len(candidates) >= 100:
            break
    return sorted(candidates, key=lambda item: (len(item.parts), item.name.lower()))


def relative_document_path(path: Path, cwd: str) -> str:
    try:
        return path.relative_to(Path(cwd).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def word_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text.lower())
        if len(token) >= 3
    ]


def looks_like_document_read_request(user_prompt: str) -> bool:
    text = user_prompt.lower()
    write_verbs = (
        "crea", "crear", "guarda", "guardar", "escribe", "escribir", "edita",
        "editar", "modifica", "modificar", "sobrescribe", "sobrescribir",
    )
    if any(verb in text for verb in write_verbs):
        return False
    read_verbs = (
        "abre", "abrir", "analiza", "analizar", "busca", "buscar", "consulta",
        "consultar", "corrige", "corregir", "extrae", "extraer", "lee", "leer",
        "resume", "resumir", "revisa", "revisar",
    )
    has_read_intent = any(verb in text for verb in read_verbs)
    has_reference = bool(_DOCUMENT_PATH_RE.search(user_prompt)) or any(
        cue in text for cue in _DOCUMENT_REQUEST_CUES
    )
    return has_read_intent and has_reference
