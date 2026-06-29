"""Read-only git helpers confined to the workspace."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ci2lab.harness.tools.paths import resolve_path


def _run_git(cwd: str, *args: str) -> str:
    """Run ``git`` with ``args`` in ``cwd`` and return its combined output.

    Args:
        cwd: Workspace directory in which to invoke git.
        *args: Arguments passed to the ``git`` executable.

    Returns:
        The combined stdout/stderr on success, or an error string describing a
        missing git binary, a timeout, or a non-zero exit.
    """
    workspace = Path(cwd).resolve()
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError:
        return "Error: git is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return "Error: git command timed out"

    out = (proc.stdout or "") + (proc.stderr or "")
    out = out.strip()
    if proc.returncode != 0:
        return (
            f"Error: git exited {proc.returncode}\n{out}"
            if out
            else f"Error: git exited {proc.returncode}"
        )
    return out or "(no output)"


def _scoped_path(cwd: str, raw: str | None) -> str | None:
    """Resolve ``raw`` within the workspace and return it relative to ``cwd``.

    Args:
        cwd: Workspace root used to scope and relativise the path.
        raw: A user-supplied path, or ``None``/blank for no path.

    Returns:
        The path relative to the workspace when possible, the resolved absolute
        path otherwise, or ``None`` when ``raw`` is empty.
    """
    if raw is None or not str(raw).strip():
        return None
    resolved = resolve_path(str(raw).strip(), cwd)
    workspace = Path(cwd).resolve()
    try:
        return str(resolved.relative_to(workspace))
    except ValueError:
        return str(resolved)


def git_status(cwd: str, path: str = ".") -> str:
    """Return ``git status --short`` for ``path``, scoped to the workspace.

    Args:
        cwd: Workspace directory in which to run git.
        path: Path to report on, relative to the workspace (defaults to all).

    Returns:
        The short-format status output, or an error string.
    """
    scoped = _scoped_path(cwd, path) or "."
    return _run_git(cwd, "status", "--short", "--", scoped)


def git_diff(cwd: str, path: str | None = None, staged: bool = False) -> str:
    """Return ``git diff`` for ``path``, scoped to the workspace.

    Args:
        cwd: Workspace directory in which to run git.
        path: Optional path to limit the diff to; ``None`` diffs everything.
        staged: When ``True``, diff staged changes (``--staged``) instead of the
            working tree.

    Returns:
        The diff output, or an error string.
    """
    args = ["diff"]
    if staged:
        args.append("--staged")
    scoped = _scoped_path(cwd, path)
    if scoped:
        args.extend(["--", scoped])
    return _run_git(cwd, *args)
