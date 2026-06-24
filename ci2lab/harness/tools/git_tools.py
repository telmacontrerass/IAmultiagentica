"""Read-only git helpers confined to the workspace."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ci2lab.harness.tools.paths import resolve_path


def _run_git(cwd: str, *args: str) -> str:
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
        return f"Error: git exited {proc.returncode}\n{out}" if out else f"Error: git exited {proc.returncode}"
    return out or "(no output)"


def _scoped_path(cwd: str, raw: str | None) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    resolved = resolve_path(str(raw).strip(), cwd)
    workspace = Path(cwd).resolve()
    try:
        return str(resolved.relative_to(workspace))
    except ValueError:
        return str(resolved)


def git_status(cwd: str, path: str = ".") -> str:
    scoped = _scoped_path(cwd, path) or "."
    return _run_git(cwd, "status", "--short", "--", scoped)


def git_diff(cwd: str, path: str | None = None, staged: bool = False) -> str:
    args = ["diff"]
    if staged:
        args.append("--staged")
    scoped = _scoped_path(cwd, path)
    if scoped:
        args.extend(["--", scoped])
    return _run_git(cwd, *args)
