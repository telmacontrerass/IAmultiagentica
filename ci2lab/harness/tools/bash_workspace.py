"""Validacion de rutas en comandos bash respecto al workspace."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

WORKSPACE_ACCESS_BLOCKED = (
    "Comando bloqueado: intenta acceder a una ruta fuera del workspace."
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
_QUOTED_PATH = re.compile(r"""['"]([^'"]+)['"]""")
_RELATIVE_PATH = re.compile(r"[^\s'\"|&;<>^]+")


def _strip_quotes(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def extract_path_candidates(command: str) -> list[str]:
    """Extrae candidatos a rutas de un comando shell."""
    if not command or not command.strip():
        return []

    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        cleaned = _strip_quotes(raw.strip().rstrip(",;"))
        if not cleaned or cleaned in seen:
            return
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            return
        if "/" not in cleaned and "\\" not in cleaned and ".." not in cleaned:
            if not _WIN_ABS_PATH.match(cleaned):
                return
        seen.add(cleaned)
        found.append(cleaned)

    for match in _WIN_ABS_PATH.finditer(command):
        add(match.group(0))

    for match in _QUOTED_PATH.finditer(command):
        add(match.group(1))

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
    """True si la ruta resuelta queda fuera del workspace."""
    if not raw_path or not str(raw_path).strip():
        return False
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
    Devuelve mensaje de bloqueo si el comando referencia rutas fuera del workspace.

    Se aplica antes de la confirmacion del usuario.
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
