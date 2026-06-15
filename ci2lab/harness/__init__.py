"""Arnés agéntico: bucle ReAct, herramientas, REPL y sesiones.

Punto de entrada principal: `run_agent` (implementado en `harness.query.loop`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.types import AgentConfig

if TYPE_CHECKING:
    from ci2lab.harness.query.loop import run_agent
    from ci2lab.harness.repl import run_repl
    from ci2lab.harness.session import (
        list_sessions,
        load_session,
        new_session_id,
        save_session,
    )

_LAZY_EXPORTS = {
    "run_agent": ("ci2lab.harness.query.loop", "run_agent"),
    "run_repl": ("ci2lab.harness.repl", "run_repl"),
    "list_sessions": ("ci2lab.harness.session", "list_sessions"),
    "load_session": ("ci2lab.harness.session", "load_session"),
    "new_session_id": ("ci2lab.harness.session", "new_session_id"),
    "save_session": ("ci2lab.harness.session", "save_session"),
}


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        import importlib

        module_path, attr = _LAZY_EXPORTS[name]
        return getattr(importlib.import_module(module_path), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def default_selection(
    ollama_tag: str = "llama3.1:8b",
    *,
    tool_mode: str | None = None,
) -> ModelSelection:
    """ModelSelection for tests/evals; uses catalog tool_mode when not overridden."""
    from ci2lab.router.selection import build_model_selection

    return build_model_selection(ollama_tag, tool_mode_override=tool_mode)


__all__ = [
    "AgentConfig",
    "ModelSelection",
    "default_selection",
    "list_sessions",
    "load_session",
    "new_session_id",
    "run_agent",
    "run_repl",
    "save_session",
]
