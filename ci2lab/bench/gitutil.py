"""Tiny git helpers for environment reset and change detection.

Bug/feat tasks take a git baseline of the agent-visible workspace before the
agent runs, so that after the run we can list exactly which files the agent
changed (to enforce ``forbid_paths`` — e.g. "do not edit the tests").
"""

from __future__ import annotations

import subprocess
from pathlib import Path

__all__ = ["changed_paths", "git_available", "init_baseline"]

_GIT_IDENTITY = [
    "-c",
    "user.email=bench@ci2lab.local",
    "-c",
    "user.name=ci2lab-bench",
]


def git_available() -> bool:
    """Return whether a ``git`` executable is callable."""
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def init_baseline(workspace: Path) -> bool:
    """Initialize a git repo in ``workspace`` and commit its current contents.

    Args:
        workspace: The directory to snapshot as the baseline.

    Returns:
        ``True`` if a baseline commit was created, ``False`` if git is
        unavailable or the commands failed (grading then skips the git check).
    """
    if not git_available():
        return False
    try:
        subprocess.run(["git", "init", "-q"], cwd=workspace, capture_output=True, check=True)
        subprocess.run(
            ["git", *_GIT_IDENTITY, "add", "-A"],
            cwd=workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", *_GIT_IDENTITY, "commit", "-q", "-m", "baseline", "--allow-empty"],
            cwd=workspace,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def changed_paths(workspace: Path) -> list[str]:
    """List workspace paths modified, added or deleted since the baseline.

    Args:
        workspace: A directory previously snapshotted by :func:`init_baseline`.

    Returns:
        Repo-relative paths that differ from the baseline (empty when git is
        unavailable or nothing changed). Untracked files are included.
    """
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        entry = line[3:].strip() if len(line) > 3 else line.strip()
        if not entry:
            continue
        if " -> " in entry:  # rename: keep the destination path
            entry = entry.split(" -> ", 1)[1]
        paths.append(entry.strip('"'))
    return paths
