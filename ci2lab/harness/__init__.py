"""Arnes agentico: bucle ReAct, herramientas, REPL y sesiones."""

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.loop import run_agent
from ci2lab.harness.repl import run_repl
from ci2lab.harness.session import list_sessions, load_session, new_session_id, save_session
from ci2lab.harness.types import AgentConfig


def default_selection(
    ollama_tag: str = "llama3.1:8b",
    *,
    tool_mode: str = "native",
) -> ModelSelection:
    """ModelSelection de prueba cuando el router aun no esta implementado."""
    try:
        from ci2lab.router.catalog import resolve_catalog_model

        model = resolve_catalog_model(ollama_tag)
    except Exception:  # noqa: BLE001
        model = None

    if model:
        return ModelSelection(
            model_id=model.id,
            ollama_tag=model.ollama_tag,
            display_name=model.display_name,
            tool_mode=model.tool_mode,
            supports_tools=model.supports_tools,
            context_length=model.context_length,
        )

    return ModelSelection(
        model_id=ollama_tag.replace(":", "-"),
        ollama_tag=ollama_tag,
        display_name=ollama_tag,
        tool_mode=tool_mode,  # type: ignore[arg-type]
        supports_tools=True,
    )


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
