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
        resolved = _resolve_prompt_path(match.group("path"), cwd)
        if resolved:
            return resolved
        # Regex matched a name that does not exist at that location (e.g. the
        # user wrote "resumen.txt inside Prueba" as prose, not as a path). Fall
        # through to candidate search so we can locate it in a subdirectory.
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


def _resolve_prompt_path(raw: str, cwd: str) -> str | None:
    """Return a usable path for a regex-matched document reference.

    Keeps the reference as-is when it already points to an existing file
    (absolute, or relative to cwd). When the prompt only named the file
    ("resumen.txt inside Prueba"), locates it by basename anywhere under cwd
    and returns the real relative path. Returns None when it cannot be resolved
    unambiguously, so the caller can fall back to token scoring.
    """
    candidate = Path(raw)
    direct = candidate if candidate.is_absolute() else Path(cwd) / raw
    if direct.is_file():
        return direct.as_posix() if candidate.is_absolute() else raw
    name = candidate.name.lower()
    matches = [path for path in document_candidates(cwd) if path.name.lower() == name]
    if len(matches) == 1:
        return relative_document_path(matches[0], cwd)
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


_WRITE_VERBS = (
    # Spanish
    "crea", "crear", "guarda", "guardar", "escribe", "escribir", "edita",
    "editar", "modifica", "modificar", "sobrescribe", "sobrescribir",
    "convierte", "convertir", "genera", "generar", "exporta", "exportar",
    # English
    "make", "create", "write", "save", "edit", "modify", "overwrite",
    "generate", "build", "convert", "export",
)
_READ_VERBS = (
    # Spanish
    "abre", "abrir", "analiza", "analizar", "busca", "buscar", "consulta",
    "consultar", "corrige", "corregir", "extrae", "extraer", "lee", "leer",
    "resume", "resumir", "revisa", "revisar",
    # English
    "read", "analyze", "analyse", "summarize", "summarise", "summary",
    "open", "review", "extract",
)
# Word-boundary match so a verb fragment inside a filename (e.g. "resume"
# inside "resumen.txt") does not falsely signal read/write intent.
_WRITE_VERB_RE = re.compile(r"\b(" + "|".join(_WRITE_VERBS) + r")\b")
_READ_VERB_RE = re.compile(r"\b(" + "|".join(_READ_VERBS) + r")\b")


def looks_like_document_read_request(user_prompt: str) -> bool:
    text = user_prompt.lower()
    if _WRITE_VERB_RE.search(text):
        return False
    has_read_intent = bool(_READ_VERB_RE.search(text))
    has_reference = bool(_DOCUMENT_PATH_RE.search(user_prompt)) or any(
        cue in text for cue in _DOCUMENT_REQUEST_CUES
    )
    return has_read_intent and has_reference
