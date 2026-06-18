"""Per-tool permissions: allow, confirm or deny."""

from __future__ import annotations

from typing import Callable

CONFIRM_TOOLS = frozenset({
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
})


def default_confirm(tool_name: str, summary: str) -> bool:
    prompt = f"\nRun {tool_name}? {summary}\n[y/N] "
    try:
        answer = input(prompt).strip().lower()  # noqa: T201
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
    if tool_name not in CONFIRM_TOOLS:
        return True, None
    if auto_confirm:
        return True, None
    callback = confirm_callback or default_confirm
    if callback(tool_name, summary):
        return True, None
    return False, f"The user denied execution of `{tool_name}`."
