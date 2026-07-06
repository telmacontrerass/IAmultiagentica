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
    "If the request names a failing test, command, or expected behaviour, run it "
    "now to confirm the real result before finishing; otherwise report the "
    "change as done."
)
_SUCCESS_HINT = (
    "The edit was applied successfully. Do not call edit_file or read_file again "
    "for the same change. Applied is not the same as working: if the request "
    "names a failing test, command, or expected behaviour, run it now and let "
    "the real output decide. Report done only after that check passes — and if "
    "it fails, keep fixing instead of finishing."
)


def edit_signature(call: ToolCall) -> EditSignature | None:
    """Return the identifying signature of an ``edit_file`` call.

    Args:
        call: The tool call to inspect.

    Returns:
        A ``(path, old_string, new_string)`` tuple identifying the edit, or
        ``None`` if the call is not an ``edit_file`` call or has no ``path``.
    """
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
    """True if old_string is gone and new_string is present (same edit repeated).

    Args:
        cwd: Workspace root used to resolve ``path``.
        path: Path to the file the edit targets.
        old_string: Text the edit expects to replace.
        new_string: Replacement text the edit would insert.

    Returns:
        ``True`` if the file exists, ``old_string`` is absent, and
        ``new_string`` is already present (so the edit has effectively been
        applied); ``False`` otherwise, including on read errors.
    """
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
    """When old_string is no longer on disk, show the current content.

    Args:
        cwd: Workspace root used to resolve ``path``.
        path: Path to the file the edit targets.
        old_string: Text the edit expected to find in the file.

    Returns:
        A hint string showing a preview of the current file content and how to
        recover, or ``None`` when ``old_string`` is empty, the file cannot be
        read, or ``old_string`` is still present on disk.
    """
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
    """Return ``True`` if ``result`` is a successful ``edit_file`` outcome."""
    return (
        not result.is_error
        and result.tool_name == "edit_file"
        and result.content.startswith(_SUCCESS_EDIT_PREFIXES)
    )


def _dedupe_hints(hints: list[str]) -> list[str]:
    """Return ``hints`` with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    unique: list[str] = []
    for hint in hints:
        if hint not in seen:
            seen.add(hint)
            unique.append(hint)
    return unique


def _has(content: str, *needles: str) -> bool:
    """Return ``True`` if any of ``needles`` is a substring of ``content``."""
    return any(needle in content for needle in needles)


def process_edit_round(
    calls: list[ToolCall],
    results: list[ToolResult],
    *,
    cwd: str,
    user_prompt: str,
    completed_edits: set[EditSignature],
) -> str | None:
    """Record successful edits and return hints for the model's next turn.

    Args:
        calls: Tool calls issued in the round, paired positionally with
            ``results``.
        results: Tool results for ``calls``, in the same order.
        cwd: Workspace root used to resolve edit paths.
        user_prompt: The user's prompt, scanned for a mentioned file path used
            to enrich hints.
        completed_edits: Mutable set of edit signatures already applied; updated
            in place with newly successful edits.

    Returns:
        A newline-joined string of deduplicated hints to surface to the model,
        or ``None`` when there is nothing to add.
    """
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
        if _has(content, "does not exist"):
            hint = (
                "The file path was wrong. Do not invent example paths like "
                "src/main.py. Call read_file first with the exact path the user "
                "gave (relative to the workspace root)."
            )
            if mentioned_path:
                hint += f" The user mentioned `{mentioned_path}`."
            hints.append(hint)
            continue

        if _has(content, "are identical"):
            hints.append(
                "old_string and new_string must be different. "
                "Read the file with read_file and change only the requested line."
            )
            continue

        if _has(content, "old_string not found"):
            if sig and (
                sig in completed_edits or edit_already_applied(cwd, sig[0], sig[1], sig[2])
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

        if _has(content, "patch context not found"):
            hints.append(
                "The patch does not apply. Call read_file, copy the real lines, "
                "and build apply_patch with those lines in the hunk."
            )

    if had_successful_edit and not had_redundant_retry:
        hints.append(_SUCCESS_HINT)

    unique = _dedupe_hints(hints)
    return "\n".join(unique) if unique else None
