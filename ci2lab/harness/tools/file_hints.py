"""Helper messages for when a file path does not exist."""

from __future__ import annotations

from pathlib import Path


def format_missing_file_error(cwd: str, resolved: Path) -> str:
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
