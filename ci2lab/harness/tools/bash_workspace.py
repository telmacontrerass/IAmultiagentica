"""Validation of paths in bash commands against the workspace."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

WORKSPACE_ACCESS_BLOCKED = (
    "Blocked command: tries to access a path outside the workspace."
)

_FILE_ACCESS_VERBS = re.compile(
    r"\b(?:"
    r"cat|type|more|less|head|tail|"
    r"get-content|gc|"
    r"copy|cp|xcopy|robocopy|move|mv|"
    r"dir|ls|ll|"
    r"select-string|sls"
    r")\b",
    re.I,
)

_WIN_ABS_PATH = re.compile(r"[A-Za-z]:[\\/][^\s'\"|&;<>^]+")
_UNC_PATH = re.compile(r"\\\\[^\s'\"|&;<>^]+")
_QUOTED_PATH = re.compile(r"""['"]([^'"]+)['"]""")
_PERCENT_ENV = re.compile(r"%([^%]+)%")
_DOLLAR_ENV = re.compile(r"\$env:([^\\\s'\"]+)", re.I)


def _expand_windows_env_refs(raw: str) -> str:
    expanded = raw
    for match in _PERCENT_ENV.finditer(raw):
        value = os.environ.get(match.group(1))
        if value:
            expanded = expanded.replace(match.group(0), value)
    for match in _DOLLAR_ENV.finditer(raw):
        value = os.environ.get(match.group(1))
        if value:
            expanded = expanded.replace(match.group(0), value)
    return expanded


def _strip_quotes(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def extract_path_candidates(command: str) -> list[str]:
    """Extract path candidates from a shell command."""
    if not command or not command.strip():
        return []

    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        cleaned = _strip_quotes(raw.strip().rstrip(",;"))
        cleaned = _expand_windows_env_refs(cleaned)
        if not cleaned or cleaned in seen:
            return
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            return
        if cleaned.startswith("\\\\") or cleaned.startswith("//"):
            seen.add(cleaned)
            found.append(cleaned)
            return
        if "/" not in cleaned and "\\" not in cleaned and ".." not in cleaned:
            if not _WIN_ABS_PATH.match(cleaned):
                if "%" in raw or "$env:" in raw.lower():
                    seen.add(cleaned)
                    found.append(cleaned)
                return
        seen.add(cleaned)
        found.append(cleaned)

    for match in _UNC_PATH.finditer(command):
        add(match.group(0))

    for match in _WIN_ABS_PATH.finditer(command):
        add(match.group(0))

    for match in _QUOTED_PATH.finditer(command):
        quoted = match.group(1)
        for nested in _UNC_PATH.finditer(quoted):
            add(nested.group(0))
        for nested in _WIN_ABS_PATH.finditer(quoted):
            add(nested.group(0))
        for nested in re.finditer(r"(?:~|/)[^\s'\"|&;<>^]+", quoted):
            add(nested.group(0))
        add(quoted)

    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        tokens = command.split()

    for token in tokens:
        if token in {"|", "||", "&&", ";", ">", ">>", "<"}:
            continue
        if "=" in token and not token.startswith(("/", "\\")) and ":" not in token[:3]:
            _, _, rhs = token.partition("=")
            if rhs:
                add(rhs)
            continue
        add(token)

    return found


def path_escapes_workspace(raw_path: str, workspace: Path) -> bool:
    """True if the resolved path falls outside the workspace."""
    if not raw_path or not str(raw_path).strip():
        return False
    raw_path = _expand_windows_env_refs(raw_path)
    if raw_path.startswith("\\\\") or raw_path.startswith("//"):
        return True
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(workspace)
        return False
    except (ValueError, OSError):
        return True


def check_bash_workspace_blocked(command: str, cwd: str) -> str | None:
    """
    Return a block message if the command references paths outside the workspace.

    Applied before asking the user for confirmation.
    """
    if not command or not command.strip():
        return None

    workspace = Path(cwd).resolve()
    normalized = command.strip()
    candidates = extract_path_candidates(normalized)
    if not candidates:
        return None

    for raw in candidates:
        if path_escapes_workspace(raw, workspace):
            return WORKSPACE_ACCESS_BLOCKED

    if ".." in normalized and _FILE_ACCESS_VERBS.search(normalized):
        for raw in candidates:
            if ".." in raw and path_escapes_workspace(raw, workspace):
                return WORKSPACE_ACCESS_BLOCKED

    return None
