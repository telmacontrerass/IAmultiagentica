"""Helper messages for when a file path does not exist."""

from __future__ import annotations

from pathlib import Path


def format_missing_file_error(cwd: str, resolved: Path) -> str:
    """Build an error message for a non-existent file path.

    The message names the missing path and, when possible, lists up to ten
    ``.py`` files in the workspace root to help the caller locate the intended
    file before retrying.

    Args:
        cwd: The current working directory whose root is scanned for hints.
        resolved: The resolved path that was found not to exist.

    Returns:
        A human-readable error string describing the missing file and a hint to
        read the exact path before editing.
    """
    base = Path(cwd).resolve()
    message = f"Error: file does not exist: {resolved}"
    try:
        root_files = sorted(base.glob("*.py"))[:10]
    except OSError:
        root_files = []
    if root_files:
        names = ", ".join(item.name for item in root_files)
        message += f". .py files in the workspace root: {names}"
    message += ". Call read_file with the exact path before editing."
    return message
