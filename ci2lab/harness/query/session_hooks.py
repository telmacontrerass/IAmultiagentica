"""Session persistence hooks for the agent loop."""

from __future__ import annotations

from typing import Any

from ci2lab.console import console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.session import save_session
from ci2lab.harness.types import AgentConfig


def maybe_save_session(
    cfg: AgentConfig,
    messages: list[dict[str, Any]],
    selection: ModelSelection,
) -> None:
    """Persist the current session to disk when a session id is configured.

    No-ops when ``cfg.session_id`` is unset. Otherwise writes the conversation
    and run metadata via :func:`save_session` and prints the saved path.

    Args:
        cfg: The active agent configuration, providing the session id, working
            directory, token usage and project id.
        messages: The conversation history to persist.
        selection: The resolved model selection, supplying the model tag.
    """
    if not cfg.session_id:
        return
    path = save_session(
        cfg.session_id,
        messages=messages,
        model_tag=selection.ollama_tag,
        cwd=cfg.cwd,
        token_usage=cfg.token_usage.to_dict(),
        project_id=cfg.project_id,
    )
    console.print(f"[dim]Session saved: {path}[/dim]")
