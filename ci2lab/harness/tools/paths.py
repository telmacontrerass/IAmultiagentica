"""Resolución segura de rutas confinadas al directorio de trabajo."""

from __future__ import annotations

from pathlib import Path

from ci2lab.security.paths import (
    PathViolationError,
    assert_within_workspace,
    is_within_workspace,
    resolve_workspace_path,
    workspace_root,
)

__all__ = [
    "PathViolationError",
    "assert_within_workspace",
    "format_size",
    "is_within_workspace",
    "resolve_path",
    "resolve_workspace_path",
    "workspace_root",
]


def resolve_path(raw: str, cwd: str) -> Path:
    """Compat: resolve_path(raw, cwd) -> resolve_workspace_path(cwd, raw)."""
    return resolve_workspace_path(cwd, raw)


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"
