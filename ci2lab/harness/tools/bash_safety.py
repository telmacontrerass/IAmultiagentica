"""Security policies for bash execution."""

from __future__ import annotations

import re

from ci2lab.harness.tools.bash_workspace import check_bash_workspace_blocked

#: Compiled (pattern, short description) pairs of always-denied command shapes.
# (pattern, short description for the user)
_BLOCKED_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\brm\s+(-[^\s]*f|-\w*f\w*|\S+\s+-rf\b)", re.I),
        "rm -rf / forced recursive deletion",
    ),
    (re.compile(r"\bdel\s+/(?:s|f|q)\b", re.I), "del /s, del /f, or del /q"),
    (re.compile(r"\bformat\s+[a-z]:", re.I), "disk format"),
    (re.compile(r"\bshutdown\b", re.I), "shutdown"),
    (re.compile(r"\breboot\b", re.I), "reboot"),
    (re.compile(r"\bcurl\b[^\n|]*\|\s*(ba)?sh\b", re.I), "curl | sh (pipe to a shell)"),
    (re.compile(r"\bwget\b[^\n|]*\|\s*(ba)?sh\b", re.I), "wget | sh (pipe to a shell)"),
    (
        re.compile(
            r"invoke-webrequest\b[^\n|]*\|\s*invoke-expression\b|"
            r"invoke-webrequest\b[^\n|]*\|\s*iex\b",
            re.I,
        ),
        "Invoke-WebRequest | iex",
    ),
    (re.compile(r"\biwr\b[^\n|]*\|\s*iex\b", re.I), "iwr | iex"),
    (
        re.compile(
            r"set-executionpolicy\s+bypass.*(invoke-webrequest|iwr|curl|wget|download)",
            re.I | re.S,
        ),
        "Set-ExecutionPolicy Bypass with download/execution",
    ),
    (
        re.compile(
            r"(invoke-webrequest|iwr|curl|wget).{0,200}set-executionpolicy\s+bypass",
            re.I | re.S,
        ),
        "download combined with Set-ExecutionPolicy Bypass",
    ),
    (re.compile(r"\binvoke-expression\b", re.I), "Invoke-Expression"),
    (re.compile(r"\biex\b", re.I), "iex (Invoke-Expression)"),
    (re.compile(r"\brm\s+\*"), "rm * (wildcard deletion)"),
    (re.compile(r"\bdel\s+\*", re.I), "del * (wildcard deletion)"),
    (
        re.compile(r"\bremove-item\s+\*", re.I),
        "Remove-Item * (wildcard deletion)",
    ),
]


def check_bash_blocked(command: str, *, cwd: str | None = None) -> str | None:
    """Return the description of the violated rule, or None if it is allowed.

    The blocklist is always applied, even with --yes.
    If cwd is passed, paths are also validated against the workspace.

    Args:
        command: The shell command line to inspect.
        cwd: Optional workspace root; when provided, referenced paths are also
            validated against it.

    Returns:
        A short description of the first violated rule, or ``None`` if the
        command is allowed.
    """
    if not command or not command.strip():
        return None
    normalized = command.strip()
    for pattern, description in _BLOCKED_RULES:
        if pattern.search(normalized):
            return description
    if cwd:
        workspace_block = check_bash_workspace_blocked(normalized, cwd)
        if workspace_block:
            return workspace_block
    return None
