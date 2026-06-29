"""Per-tool permissions: allow, confirm or deny."""

from __future__ import annotations

from collections.abc import Callable

from ci2lab.console import active_progress

CONFIRM_TOOLS = frozenset(
    {
        "bash",
        "write_file",
        "edit_file",
        "write_docx",
        "apply_patch",
        "fill_docx_template",
        "docx_to_pdf",
        "pdf_to_docx",
        "web_fetch",
        "notebook_edit",
    }
)


def default_confirm(tool_name: str, summary: str) -> bool:
    """Prompt the user on the console to confirm running a tool.

    Suspends the active progress spinner so the prompt is visible.

    Args:
        tool_name: Name of the tool awaiting confirmation.
        summary: Short human-readable description of what the tool will do.

    Returns:
        ``True`` if the user answers yes; ``False`` otherwise, including on EOF.
    """
    prompt = f"\nRun {tool_name}? {summary}\n[y/N] "
    try:
        # Pause the "thinking" spinner so it doesn't hide this prompt.
        with active_progress.suspended():
            answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def check_permission(
    tool_name: str,
    summary: str,
    *,
    auto_confirm: bool,
    confirm_callback: Callable[[str, str], bool] | None = None,
) -> tuple[bool, str | None]:
    """Decide whether a tool may run, prompting for confirmation when required.

    Tools outside :data:`CONFIRM_TOOLS` are always allowed. Tools inside it are
    allowed automatically when ``auto_confirm`` is set; otherwise the user is
    asked via ``confirm_callback`` (or :func:`default_confirm`).

    Args:
        tool_name: Name of the tool requesting permission.
        summary: Short description passed to the confirmation prompt.
        auto_confirm: When ``True``, skip the prompt and allow the call.
        confirm_callback: Optional custom confirmation function; defaults to
            :func:`default_confirm`.

    Returns:
        A ``(allowed, denial_message)`` tuple; ``denial_message`` is ``None``
        when allowed and a user-facing reason string when denied.
    """
    if tool_name not in CONFIRM_TOOLS:
        return True, None
    if auto_confirm:
        return True, None
    callback = confirm_callback or default_confirm
    if callback(tool_name, summary):
        return True, None
    return False, f"The user denied execution of `{tool_name}`."
