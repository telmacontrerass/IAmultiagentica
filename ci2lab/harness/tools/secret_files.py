"""Politica de archivos sensibles dentro del workspace."""

from __future__ import annotations

import re
from pathlib import Path

POLICY_SECRET_FILE_BLOCKED = "POLICY_SECRET_FILE_BLOCKED"

_TOKEN_SPLIT = re.compile(r"[._\-\s]+")

_SENSITIVE_NAME_TOKENS = frozenset({
    "token",
    "secret",
    "secrets",
    "password",
    "passwords",
    "credential",
    "credentials",
})

_SENSITIVE_TOKEN_PAIRS = frozenset({
    ("api", "key"),
    ("private", "key"),
})

_SENSITIVE_EXACT_NAMES = frozenset({"id_rsa", "id_ed25519"})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def secret_file_block_message() -> str:
    return (
        f"Error: {POLICY_SECRET_FILE_BLOCKED}: no se puede leer archivos sensibles "
        "(secretos, credenciales, claves o tokens)."
    )


def _basename_stem(name: str) -> str:
    if name.startswith("."):
        return name
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def _split_name_tokens(name: str) -> list[str]:
    stem = _basename_stem(name)
    return [part for part in _TOKEN_SPLIT.split(stem.lower()) if part]


def _tokens_are_sensitive(tokens: list[str]) -> bool:
    if any(token in _SENSITIVE_NAME_TOKENS for token in tokens):
        return True
    for idx in range(len(tokens) - 1):
        if (tokens[idx], tokens[idx + 1]) in _SENSITIVE_TOKEN_PAIRS:
            return True
    return False


def _is_sensitive_basename(name: str) -> bool:
    """Evalúa un componente de ruta (nombre de archivo o carpeta)."""
    lower = name.lower()
    if lower == ".env" or lower.startswith(".env."):
        return True
    if lower in _SENSITIVE_EXACT_NAMES or lower.startswith("id_rsa") or lower.startswith(
        "id_ed25519"
    ):
        return True
    if any(lower.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES):
        return True
    return _tokens_are_sensitive(_split_name_tokens(name))


def _sensitive_parts(path: Path, workspace: Path | str | None) -> list[str]:
    resolved = path.resolve()
    if workspace is not None:
        base = Path(workspace).resolve()
        try:
            return list(resolved.relative_to(base).parts)
        except ValueError:
            return [resolved.name]
    return [resolved.name]


def is_sensitive_path(path: Path, *, workspace: Path | str | None = None) -> bool:
    """
    True si la ruta resuelta parece contener secretos o credenciales.

    Si se pasa ``workspace``, solo se evalúan componentes relativos al workspace
    (evita falsos positivos por nombres de carpetas del SO o del runner de tests).
    Sin workspace, solo se evalúa el basename del archivo objetivo.
    """
    return any(_is_sensitive_basename(part) for part in _sensitive_parts(path, workspace))


def grep_skip_notice(skipped: int) -> str:
    if skipped <= 0:
        return ""
    return (
        f"(politica: se omitieron {skipped} archivo(s) sensible(s) de la busqueda)"
    )
