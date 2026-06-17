"""Path normalization and confinement to the workspace."""

from __future__ import annotations

from pathlib import Path


class PathViolationError(ValueError):
    """The path escapes the allowed directory."""


def workspace_root(workspace: str) -> Path:
    return Path(workspace).resolve()


def is_within_workspace(requested_path: str, workspace: str) -> bool:
    """True if requested_path resolves inside the workspace."""
    base = workspace_root(workspace)
    candidate = Path(requested_path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        candidate.resolve().relative_to(base)
        return True
    except (ValueError, OSError):
        return False


def resolve_workspace_path(workspace: str, requested_path: str) -> Path:
    """Resolve requested_path relative to the workspace and reject path traversal."""
    base = workspace_root(workspace)
    candidate = Path(requested_path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise PathViolationError(
            f"Path outside the workspace: {resolved} (base: {base})"
        ) from exc
    return resolved


def assert_within_workspace(workspace: str, requested_path: str) -> Path:
    """Explicit alias that raises if the path escapes the workspace."""
    return resolve_workspace_path(workspace, requested_path)
