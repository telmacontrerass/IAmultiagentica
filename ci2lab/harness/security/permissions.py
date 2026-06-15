"""Permisos por herramienta: allow, confirm o deny."""

from __future__ import annotations

from typing import Callable

CONFIRM_TOOLS = frozenset({
    "bash",
    "write_file",
    "edit_file",
    "write_docx",
    "apply_patch",
    "fill_docx_template",
    "web_fetch",
    "notebook_edit",
})


def default_confirm(tool_name: str, summary: str) -> bool:
    prompt = f"\n¿Ejecutar {tool_name}? {summary}\n[s/N] "
    try:
        answer = input(prompt).strip().lower()  # noqa: T201
    except EOFError:
        return False
    return answer in {"s", "si", "sí", "y", "yes"}


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
    return False, f"El usuario denegó la ejecución de `{tool_name}`."
