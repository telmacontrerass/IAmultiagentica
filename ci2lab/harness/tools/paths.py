"""Resolución segura de rutas confinadas al directorio de trabajo."""

from __future__ import annotations

import os
from pathlib import Path


class PathViolationError(ValueError):
    """La ruta escapa del directorio permitido."""


def resolve_path(raw: str, cwd: str) -> Path:
    """Resuelve raw respecto a cwd y rechaza path traversal."""
    base = Path(cwd).resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise PathViolationError(
            f"Ruta fuera del proyecto: {resolved} (base: {base})"
        ) from exc
    return resolved


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"
