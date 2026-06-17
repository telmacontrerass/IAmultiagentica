"""Redirige `bash <tool> ...` al tool nativo cuando el modelo se equivoca.

Cubre dos casos:

1. El modelo escribe `bash read_file ...` (un tool nativo dentro de un bloque
   bash). Lo mapeamos al tool real.
2. El modelo escribe comandos POSIX (`ls`, `grep`, `find`, `cat`, ...) dentro de
   un bloque `bash`, pero el skill activo no permite `bash`. Traducimos esos
   comandos al tool equivalente (`ls`, `grep`, `glob`, `read_file`) para que la
   tarea avance en vez de quedarse en bucle contra el filtro de permisos.
"""

from __future__ import annotations

import shlex

from ci2lab.harness.types import ToolCall

# Tools nativos que no existen como comando de shell (p. ej. read_file en Windows).
_REDIRECTABLE_TOOLS = frozenset({
    "read_file",
    "read_document",
    "write_file",
    "edit_file",
    "apply_patch",
    "file_info",
    "tree",
    "inspect_file",
    "todo_write",
    "ask_user",
    "notebook_edit",
    "skill",
})

# Caracteres de shell que indican composición real (pipes, redirecciones,
# subshells, encadenado). Si aparecen fuera de un caso simple, no traducimos.
_SHELL_CONTROL = ("&&", "||", ";", ">", "<", "$(", "`", "&")

_GLOB_CHARS = ("*", "?", "[")


def _looks_glob(token: str) -> bool:
    return any(ch in token for ch in _GLOB_CHARS)


def _safe_split(segment: str) -> list[str] | None:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _translate_simple_shell(command: str) -> tuple[str, dict] | None:
    """Traduce un comando POSIX simple al tool equivalente.

    Devuelve (tool_name, args) o None si no hay equivalencia segura.
    Para pipelines `ls ... | grep X` usa solo el primer segmento: así el
    modelo recibe el listado completo y puede continuar.
    """
    stripped = command.strip()
    if not stripped:
        return None

    # Pipelines: nos quedamos con el primer comando (el listado/lectura base).
    segment = stripped.split("|", 1)[0].strip()
    if not segment:
        return None

    # Construcciones de shell complejas (redirecciones, encadenado): no tocar.
    if any(ctrl in segment for ctrl in _SHELL_CONTROL):
        return None

    tokens = _safe_split(segment)
    if not tokens:
        return None

    cmd = tokens[0].lower()
    rest = tokens[1:]
    # Operandos no-flag (ignora -l, -a, -name, etc.).
    operands = [t for t in rest if not t.startswith("-")]

    if cmd in ("ls", "dir", "ll"):
        if operands and _looks_glob(operands[0]):
            return "glob", {"pattern": operands[0]}
        return "ls", {"path": operands[0] if operands else "."}

    if cmd == "find":
        # `find <base> -name <patrón>` → glob recursivo.
        name = None
        for flag in ("-name", "-iname"):
            if flag in rest:
                idx = rest.index(flag)
                if idx + 1 < len(rest):
                    name = rest[idx + 1]
                    break
        base = operands[0] if operands else "."
        if name:
            pattern = name if "/" in name else f"**/{name}"
            return "glob", {"pattern": pattern, "path": base}
        return "ls", {"path": base}

    if cmd == "glob":
        # `bash glob **/x` (glob no es comando de shell): redirige al tool.
        if operands:
            return "glob", {"pattern": operands[0]}
        return None

    if cmd in ("grep", "egrep", "fgrep", "rg"):
        ignore_case = any(t in ("-i", "-I") for t in rest if t.startswith("-"))
        if not operands:
            return None
        pattern = operands[0]
        args: dict = {"pattern": pattern}
        if ignore_case:
            args["ignore_case"] = True
        if len(operands) > 1:
            args["path"] = operands[1]
        return "grep", args

    if cmd in ("cat", "head", "tail", "less", "more", "bat"):
        if operands:
            return "read_file", {"path": operands[0]}
        return None

    return None


def _build_call(tool_name: str, tool_args: dict, call_id: str | None) -> ToolCall:
    from ci2lab.harness.parsing import _new_call

    call = _new_call(tool_name, tool_args)
    if call_id:
        return ToolCall(name=call.name, arguments=call.arguments, call_id=call_id)
    return call


def tool_call_from_bash_command(
    command: str,
    *,
    call_id: str | None = None,
) -> ToolCall | None:
    """Redirige `bash read_file ...` (un tool nativo escrito como comando) al tool.

    Solo cubre nombres de tool que NO son comandos de shell reales. La traducción
    de comandos POSIX genuinos (`ls`, `grep`, ...) vive en `shell_command_to_tool`
    y solo se aplica cuando el skill bloquea `bash`.
    """
    from ci2lab.harness.parsing import _fenced_body_to_args, _map_name

    stripped = command.strip()
    if not stripped:
        return None
    parts = stripped.split(None, 1)
    mapped = _map_name(parts[0])
    if mapped not in _REDIRECTABLE_TOOLS:
        return None
    rest = parts[1].strip() if len(parts) > 1 else ""
    args = _fenced_body_to_args(mapped, rest or stripped)
    return _build_call(mapped, args, call_id)


def shell_command_to_tool(
    command: str,
    *,
    call_id: str | None = None,
) -> ToolCall | None:
    """Traduce un comando POSIX simple (`ls`, `grep`, `find`, `cat`) al tool nativo.

    Pensado como red de seguridad cuando un skill no permite `bash`: así el modelo
    avanza usando la herramienta permitida en vez de quedarse en bucle.
    """
    translated = _translate_simple_shell(command)
    if translated is None:
        return None
    tool_name, tool_args = translated
    return _build_call(tool_name, tool_args, call_id)


def redirect_bash_call(call: ToolCall) -> ToolCall:
    """Si `bash` en realidad invoca otra herramienta (`bash read_file ...`), redirige."""
    if call.name != "bash":
        return call
    command = str(call.arguments.get("command", ""))
    redirected = tool_call_from_bash_command(command, call_id=call.call_id)
    return redirected if redirected is not None else call
