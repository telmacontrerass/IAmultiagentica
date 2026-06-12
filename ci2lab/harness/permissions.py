"""Permisos por herramienta: allow, confirm o deny."""

from __future__ import annotations

from typing import Callable

# Herramientas que requieren confirmación explícita del usuario en MVP.
CONFIRM_TOOLS = frozenset({
    "bash",
    "write_file",
    "edit_file",
    "web_fetch",
    "notebook_edit",
})


def default_confirm(tool_name: str, summary: str) -> bool:
    """Pregunta en terminal. Devuelve True si el usuario aprueba."""
    prompt = f"\n¿Ejecutar {tool_name}? {summary}\n[s/N] "
    try:
        answer = input(prompt).strip().lower()
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
    """
    Devuelve (allowed, error_message).
    error_message solo si denied.
    """
    if tool_name not in CONFIRM_TOOLS:
        return True, None
    if auto_confirm:
        return True, None
    callback = confirm_callback or default_confirm
    if callback(tool_name, summary):
        return True, None
    return False, f"El usuario denegó la ejecución de `{tool_name}`."
