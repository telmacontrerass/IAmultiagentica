"""Redirige `bash read_file ...` al tool nativo cuando el modelo se equivoca."""

from __future__ import annotations

from ci2lab.harness.types import ToolCall

# Solo herramientas que no existen como comando de shell (p. ej. read_file en Windows).
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


def tool_call_from_bash_command(
    command: str,
    *,
    call_id: str | None = None,
) -> ToolCall | None:
    from ci2lab.harness.parsing import _fenced_body_to_args, _map_name, _new_call

    stripped = command.strip()
    if not stripped:
        return None
    parts = stripped.split(None, 1)
    mapped = _map_name(parts[0])
    if mapped not in _REDIRECTABLE_TOOLS:
        return None
    rest = parts[1].strip() if len(parts) > 1 else ""
    args = _fenced_body_to_args(mapped, rest or stripped)
    call = _new_call(mapped, args)
    if call_id:
        return ToolCall(
            name=call.name,
            arguments=call.arguments,
            call_id=call_id,
        )
    return call


def redirect_bash_call(call: ToolCall) -> ToolCall:
    """Si `bash` en realidad invoca otra herramienta (`bash read_file ...`), redirige."""
    if call.name != "bash":
        return call
    command = str(call.arguments.get("command", ""))
    redirected = tool_call_from_bash_command(command, call_id=call.call_id)
    return redirected if redirected is not None else call
