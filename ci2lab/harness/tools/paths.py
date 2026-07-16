"""Safe resolution of paths confined to the working directory."""

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
    "display_path",
    "format_size",
    "is_within_workspace",
    "resolve_path",
    "resolve_workspace_path",
    "workspace_root",
]


def resolve_path(raw: str, cwd: str) -> Path:
    """Resolve ``raw`` against ``cwd``, confined to the workspace.

    Backwards-compatible wrapper that flips the argument order of
    :func:`resolve_workspace_path`: ``resolve_path(raw, cwd)`` is equivalent to
    ``resolve_workspace_path(cwd, raw)``.

    Args:
        raw: The user/agent-supplied path, absolute or workspace-relative.
        cwd: The current working directory used as the resolution base.

    Returns:
        The resolved absolute :class:`~pathlib.Path`, guaranteed to lie within
        the workspace root.

    Raises:
        PathViolationError: If the resolved path escapes the workspace root.
    """
    return resolve_workspace_path(cwd, raw)


def display_path(resolved: Path, cwd: str) -> str:
    """Return a path relative to ``cwd`` when possible, otherwise as absolute."""
    try:
        return str(resolved.relative_to(Path(cwd).resolve()))
    except ValueError:
        return str(resolved)


def format_size(num_bytes: int) -> str:
    """Format a byte count as a human-readable size string.

    Args:
        num_bytes: The size in bytes.

    Returns:
        The size rendered with a ``B``, ``KB`` or ``MB`` suffix (e.g. ``"1.5 KB"``).
    """
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"
