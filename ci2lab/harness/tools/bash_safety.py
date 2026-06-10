"""Políticas de seguridad para ejecución bash."""

from __future__ import annotations

import re

from ci2lab.harness.tools.bash_workspace import check_bash_workspace_blocked

# (patrón, descripción corta para el usuario)
_BLOCKED_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[^\s]*f|-\w*f\w*|\S+\s+-rf\b)", re.I), "rm -rf / eliminación recursiva forzada"),
    (re.compile(r"\bdel\s+/(?:s|f|q)\b", re.I), "del /s, del /f o del /q"),
    (re.compile(r"\bformat\s+[a-z]:", re.I), "format de disco"),
    (re.compile(r"\bshutdown\b", re.I), "shutdown"),
    (re.compile(r"\breboot\b", re.I), "reboot"),
    (re.compile(r"\bcurl\b[^\n|]*\|\s*(ba)?sh\b", re.I), "curl | sh (pipe a shell)"),
    (re.compile(r"\bwget\b[^\n|]*\|\s*(ba)?sh\b", re.I), "wget | sh (pipe a shell)"),
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
        "Set-ExecutionPolicy Bypass con descarga/ejecución",
    ),
    (
        re.compile(
            r"(invoke-webrequest|iwr|curl|wget).{0,200}set-executionpolicy\s+bypass",
            re.I | re.S,
        ),
        "descarga combinada con Set-ExecutionPolicy Bypass",
    ),
]


def check_bash_blocked(command: str, *, cwd: str | None = None) -> str | None:
    """Devuelve la descripción de la regla violada, o None si está permitido.

    La blocklist se aplica siempre, incluso con --yes.
    Si se pasa cwd, también se validan rutas respecto al workspace.
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
