"""Politica de archivos sensibles dentro del workspace."""

from __future__ import annotations

from pathlib import Path

POLICY_SECRET_FILE_BLOCKED = "POLICY_SECRET_FILE_BLOCKED"

_SECRET_NAME_MARKERS = ("secret", "credentials", "token")
_SENSITIVE_EXACT_NAMES = frozenset({"id_rsa", "id_ed25519"})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def secret_file_block_message() -> str:
    return (
        f"Error: {POLICY_SECRET_FILE_BLOCKED}: no se puede leer archivos sensibles "
        "(secretos, credenciales, claves o tokens)."
    )


def is_sensitive_path(path: Path) -> bool:
    """True si la ruta resuelta parece contener secretos o credenciales."""
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    if name in _SENSITIVE_EXACT_NAMES or name.startswith("id_rsa") or name.startswith(
        "id_ed25519"
    ):
        return True
    if any(name.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES):
        return True
    normalized = path.as_posix().lower()
    return any(marker in normalized for marker in _SECRET_NAME_MARKERS)


def grep_skip_notice(skipped: int) -> str:
    if skipped <= 0:
        return ""
    return (
        f"(politica: se omitieron {skipped} archivo(s) sensible(s) de la busqueda)"
    )
