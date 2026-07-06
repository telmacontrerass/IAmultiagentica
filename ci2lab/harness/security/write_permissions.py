"""Confirmation with diff preview for write tools."""

from __future__ import annotations

from collections.abc import Callable

from rich.panel import Panel

from ci2lab.console import console
from ci2lab.harness.security.permissions import check_permission, default_confirm
from ci2lab.harness.tools.write_preview import WritePreview
from ci2lab.harness.types import AgentConfig

WRITE_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "write_docx",
        "write_pptx",
        "apply_patch",
        "fill_docx_template",
        "docx_to_pdf",
        "pdf_to_docx",
    }
)


def check_write_permission(
    tool_name: str,
    preview: WritePreview,
    config: AgentConfig,
) -> tuple[bool, str | None]:
    """Decide whether a write/mutating tool may run, showing a diff when configured.

    Rejects invalid previews outright. When the config requests a diff preview,
    confirmation is gathered with the rendered diff; otherwise it falls back to
    the standard path-based permission check.

    Args:
        tool_name: Name of the write tool requesting permission.
        preview: The validated preview of the pending write/diff.
        config: Agent configuration controlling confirmation behavior.

    Returns:
        A ``(allowed, denial_message)`` tuple; ``denial_message`` is ``None``
        when allowed and a user-facing reason when denied or invalid.
    """
    if not preview.is_valid:
        return False, preview.validation_error

    if config.require_diff_preview:
        return _confirm_with_preview(tool_name, preview, config.confirm_callback)

    from ci2lab.harness.tools.filesystem import permission_summary

    return check_permission(
        tool_name,
        permission_summary(tool_name, {"path": preview.path}),
        auto_confirm=config.auto_confirm,
        confirm_callback=config.confirm_callback,
    )


def _confirm_with_preview(
    tool_name: str,
    preview: WritePreview,
    confirm_callback: Callable[[str, str], bool] | None,
) -> tuple[bool, str | None]:
    """Render the write preview as a panel and ask the user to confirm it.

    Args:
        tool_name: Name of the write tool requesting permission.
        preview: The preview whose formatted diff is shown to the user.
        confirm_callback: Optional confirmation function; defaults to
            :func:`default_confirm` using the preview path.

    Returns:
        A ``(allowed, denial_message)`` tuple; ``denial_message`` is ``None``
        when approved and a user-facing reason when denied.
    """
    body = preview.format_for_display()
    console.print(Panel(body, title=f"Preview: {tool_name}", border_style="yellow"))

    if confirm_callback is not None:
        approved = confirm_callback(tool_name, body)
    else:
        approved = default_confirm(tool_name, preview.path)

    if approved:
        return True, None
    return False, f"The user denied execution of `{tool_name}`."
