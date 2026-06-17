"""Follow-up messages after edit_file to avoid redundant rounds.

The content checks below match tool output in both English and (legacy) Spanish
so they keep working regardless of the language a tool emits its error in.
"""

from __future__ import annotations

import re

from ci2lab.harness.tools.paths import resolve_path
from ci2lab.harness.types import ToolCall, ToolResult

_FILE_IN_PROMPT_RE = re.compile(
    r"(?P<path>[^\s`\"']+\.(?:py|md|txt|json|yaml|yml))\b",
    re.IGNORECASE,
)

EditSignature = tuple[str, str, str]

_SUCCESS_EDIT_PREFIXES = ("Edited ", "Editado ")
_ALREADY_APPLIED_HINT = (
    "This change is already applied in the file. "
    "Do not repeat edit_file with the same old_string. "
    "Tell the user the change is done; do not call more tools unless they ask "
    "for a different change."
)
_SUCCESS_HINT = (
    "The edit was applied successfully. "
    "Tell the user the result; do not call edit_file or read_file again for the "
    "same change."
)


def edit_signature(call: ToolCall) -> EditSignature | None:
    if call.name != "edit_file":
        return None
    path = str(call.arguments.get("path", ""))
    if not path:
        return None
    return (
        path,
        str(call.arguments.get("old_string", "")),
        str(call.arguments.get("new_string", "")),
    )


def edit_already_applied(cwd: str, path: str, old_string: str, new_string: str) -> bool:
    """True if old_string is gone and new_string is present (same edit repeated)."""
    if not new_string:
        return False
    try:
        resolved = resolve_path(path, cwd)
        if not resolved.is_file():
            return False
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if old_string and old_string in text:
        return False
    return new_string in text


def stale_old_string_hint(cwd: str, path: str, old_string: str) -> str | None:
    """When old_string is no longer on disk, show the current content."""
    if not old_string:
        return None
    try:
        resolved = resolve_path(path, cwd)
        if not resolved.is_file():
            return None
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if old_string in text:
        return None
    lines = text.splitlines()
    preview = "\n".join(f"  {index + 1}|{line}" for index, line in enumerate(lines[:12]))
    if len(lines) > 12:
        preview += f"\n  ... ({len(lines)} lines total)"
    return (
        f"`{old_string}` is no longer in `{path}`; the file changed since the last read. "
        f"Current content:\n{preview}\n"
        "Call read_file and use the exact text of the line to change as old_string."
    )


def _is_successful_edit(result: ToolResult) -> bool:
    return (
        not result.is_error
        and result.tool_name == "edit_file"
        and result.content.startswith(_SUCCESS_EDIT_PREFIXES)
    )


def _dedupe_hints(hints: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for hint in hints:
        if hint not in seen:
            seen.add(hint)
            unique.append(hint)
    return unique


def _has(content: str, *needles: str) -> bool:
    return any(needle in content for needle in needles)


def process_edit_round(
    calls: list[ToolCall],
    results: list[ToolResult],
    *,
    cwd: str,
    user_prompt: str,
    completed_edits: set[EditSignature],
) -> str | None:
    """Record successful edits and return hints for the model's next turn."""
    hints: list[str] = []
    had_successful_edit = False
    had_redundant_retry = False
    mentioned = _FILE_IN_PROMPT_RE.findall(user_prompt)
    mentioned_path = mentioned[0] if mentioned else None

    for call, result in zip(calls, results, strict=False):
        sig = edit_signature(call)
        if sig and _is_successful_edit(result):
            completed_edits.add(sig)
            had_successful_edit = True

        if not result.is_error:
            continue
        if result.tool_name not in {"edit_file", "write_file", "apply_patch"}:
            continue

        content = result.content
        if _has(content, "does not exist", "no existe el archivo"):
            hint = (
                "The file path was wrong. Do not invent example paths like "
                "src/main.py. Call read_file first with the exact path the user "
                "gave (relative to the workspace root)."
            )
            if mentioned_path:
                hint += f" The user mentioned `{mentioned_path}`."
            hints.append(hint)
            continue

        if _has(content, "are identical", "old_string y new_string son iguales"):
            hints.append(
                "old_string and new_string must be different. "
                "Read the file with read_file and change only the requested line."
            )
            continue

        if _has(content, "old_string not found", "old_string no encontrado"):
            if sig and (
                sig in completed_edits
                or edit_already_applied(cwd, sig[0], sig[1], sig[2])
            ):
                hints.append(_ALREADY_APPLIED_HINT)
                had_redundant_retry = True
            else:
                stale = stale_old_string_hint(cwd, sig[0], sig[1]) if sig else None
                hints.append(
                    stale
                    or (
                        "old_string does not match the current file. "
                        "Call read_file again and copy the exact text of the line to change."
                    )
                )
            continue

        if _has(content, "patch context not found", "no se encontró contexto del parche"):
            hints.append(
                "The patch does not apply. Call read_file, copy the real lines, "
                "and build apply_patch with those lines in the hunk."
            )

    if had_successful_edit and not had_redundant_retry:
        hints.append(_SUCCESS_HINT)

    unique = _dedupe_hints(hints)
    return "\n".join(unique) if unique else None
