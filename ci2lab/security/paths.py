"""Path normalization and confinement to the workspace."""

from __future__ import annotations

from pathlib import Path


class PathViolationError(ValueError):
    """Raised when a requested path escapes the allowed directory."""


def workspace_root(workspace: str) -> Path:
    """Resolve the workspace directory to an absolute, normalized path.

    Args:
        workspace: Path to the workspace root.

    Returns:
        The resolved absolute :class:`~pathlib.Path` of the workspace.
    """
    return Path(workspace).resolve()


def is_within_workspace(requested_path: str, workspace: str) -> bool:
    """Return whether ``requested_path`` resolves inside the workspace.

    Args:
        requested_path: Path to test, absolute or relative to the workspace.
        workspace: Path to the workspace root.

    Returns:
        True if the resolved path is contained in the workspace, else False.
    """
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
    """Resolve ``requested_path`` against the workspace, rejecting traversal.

    Args:
        workspace: Path to the workspace root.
        requested_path: Path to resolve, absolute or relative to the workspace.

    Returns:
        The resolved absolute path, guaranteed to be inside the workspace.

    Raises:
        PathViolationError: If the resolved path escapes the workspace.
    """
    base = workspace_root(workspace)
    candidate = Path(requested_path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise PathViolationError(f"Path outside the workspace: {resolved} (base: {base})") from exc
    return resolved


def assert_within_workspace(workspace: str, requested_path: str) -> Path:
    """Explicit alias of :func:`resolve_workspace_path`.

    Args:
        workspace: Path to the workspace root.
        requested_path: Path to resolve, absolute or relative to the workspace.

    Returns:
        The resolved absolute path, guaranteed to be inside the workspace.

    Raises:
        PathViolationError: If the resolved path escapes the workspace.
    """
    return resolve_workspace_path(workspace, requested_path)
