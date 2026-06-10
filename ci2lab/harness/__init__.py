"""Arnes agentico: bucle ReAct, herramientas, REPL y sesiones."""

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.loop import run_agent
from ci2lab.harness.repl import run_repl
from ci2lab.harness.session import list_sessions, load_session, new_session_id, save_session
from ci2lab.harness.types import AgentConfig


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
