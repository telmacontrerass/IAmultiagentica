"""Confirmación con diff preview para herramientas de escritura."""

from __future__ import annotations

from typing import Callable

from rich.panel import Panel

from ci2lab.console import console
from ci2lab.harness.security.permissions import check_permission, default_confirm
from ci2lab.harness.tools.write_preview import WritePreview
from ci2lab.harness.types import AgentConfig

_console = console

WRITE_TOOLS = frozenset(
    {"write_file", "edit_file", "write_docx", "apply_patch", "fill_docx_template"}
)


def check_write_permission(
    tool_name: str,
    preview: WritePreview,
    config: AgentConfig,
) -> tuple[bool, str | None]:
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
    body = preview.format_for_display()
    _console.print(Panel(body, title=f"Preview: {tool_name}", border_style="yellow"))

    if confirm_callback is not None:
        approved = confirm_callback(tool_name, body)
    else:
        approved = default_confirm(tool_name, preview.path)

    if approved:
        return True, None
    return False, f"El usuario denegó la ejecución de `{tool_name}`."
