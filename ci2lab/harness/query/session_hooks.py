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
    if not cfg.session_id:
        return
    path = save_session(
        cfg.session_id,
        messages=messages,
        model_tag=selection.ollama_tag,
        cwd=cfg.cwd,
        token_usage=cfg.token_usage.to_dict(),
    )
    console.print(f"[dim]Session saved: {path}[/dim]")
