"""Redirect `bash <tool> ...` to the native tool when the model gets it wrong.

Covers two cases:

1. The model writes `bash read_file ...` (a native tool inside a bash
   block). We map it to the real tool.
2. The model writes POSIX commands (`ls`, `grep`, `find`, `cat`, ...) inside
   a `bash` block, but the active skill does not allow `bash`. We translate those
   commands to the equivalent tool (`ls`, `grep`, `glob`, `read_file`) so the
   task moves forward instead of looping against the permission filter.
"""

from __future__ import annotations

import shlex

from ci2lab.harness.types import ToolCall

# Native tools that do not exist as a shell command (e.g. read_file on Windows).
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

# Shell characters that indicate real composition (pipes, redirections,
# subshells, chaining). If they appear outside a simple case, we don't translate.
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
    """Translate a simple POSIX command to the equivalent tool.

    Returns (tool_name, args) or None if there is no safe equivalence.
    For pipelines `ls ... | grep X` it uses only the first segment: that way the
    model receives the full listing and can continue.
    """
    stripped = command.strip()
    if not stripped:
        return None

    # Pipelines: keep the first command (the base listing/read).
    segment = stripped.split("|", 1)[0].strip()
    if not segment:
        return None

    # Complex shell constructs (redirections, chaining): don't touch.
    if any(ctrl in segment for ctrl in _SHELL_CONTROL):
        return None

    tokens = _safe_split(segment)
    if not tokens:
        return None

    cmd = tokens[0].lower()
    rest = tokens[1:]
    # Non-flag operands (ignores -l, -a, -name, etc.).
    operands = [t for t in rest if not t.startswith("-")]

    if cmd in ("ls", "dir", "ll"):
        if operands and _looks_glob(operands[0]):
            return "glob", {"pattern": operands[0]}
        return "ls", {"path": operands[0] if operands else "."}

    if cmd == "find":
        # `find <base> -name <pattern>` → recursive glob.
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
        # `bash glob **/x` (glob is not a shell command): redirect to the tool.
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
    """Redirect `bash read_file ...` (a native tool written as a command) to the tool.

    Only covers tool names that are NOT real shell commands. The translation
    of genuine POSIX commands (`ls`, `grep`, ...) lives in `shell_command_to_tool`
    and is only applied when the skill blocks `bash`.
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
    """Translate a simple POSIX command (`ls`, `grep`, `find`, `cat`) to the native tool.

    Intended as a safety net when a skill does not allow `bash`: that way the model
    moves forward using the permitted tool instead of looping.
    """
    translated = _translate_simple_shell(command)
    if translated is None:
        return None
    tool_name, tool_args = translated
    return _build_call(tool_name, tool_args, call_id)


def redirect_bash_call(call: ToolCall) -> ToolCall:
    """If `bash` actually invokes another tool (`bash read_file ...`), redirect it."""
    if call.name != "bash":
        return call
    command = str(call.arguments.get("command", ""))
    redirected = tool_call_from_bash_command(command, call_id=call.call_id)
    return redirected if redirected is not None else call
