"""
Pipeline de preparación: hardware + selección de modelo para el arnés.

El router (models recommend) sugiere modelos; el usuario elige cuál ejecutar.
Al arrancar chat/agent se aplica el tool_mode del catálogo para ese modelo.
"""

from __future__ import annotations

import os
from typing import Callable

from ci2lab.config import DEFAULT_MODEL, Ci2LabConfig
from ci2lab.contracts.types import HardwareProfile, ModelSelection
from ci2lab.hardware import scan_hardware
from ci2lab.harness.types import AgentConfig
from ci2lab.router.selection import build_model_selection


def prepare_session(
    user_prompt: str,
    *,
    force_model: str | None = None,
    tool_mode_override: str | None = None,
    backend_url: str | None = None,
    pull: bool = True,
) -> tuple[HardwareProfile | None, ModelSelection]:
    """
    Prepara una sesión del arnés para el modelo que el usuario eligió.

    - No auto-selecciona modelo desde el router (eso es `ci2lab models recommend`).
    - Aplica tool_mode del catálogo para el tag elegido.
    - `tool_mode_override` solo cuando el usuario pasa --tool-mode en CLI.
    """
    _ = user_prompt

    profile = scan_hardware()
    tag = force_model or os.environ.get("CI2LAB_MODEL", DEFAULT_MODEL)
    selection = build_model_selection(
        tag,
        tool_mode_override=tool_mode_override,
        backend_url=backend_url,
        profile=profile,
    )

    if pull:
        _maybe_ensure_model_ready(selection)

    return profile, selection


def _maybe_ensure_model_ready(selection: ModelSelection) -> None:
    try:
        from ci2lab.runtime.ensure import ensure_model_ready
    except ImportError:
        return
    ensure_model_ready(selection)


def build_agent_config(
    runtime: Ci2LabConfig,
    selection: ModelSelection,
    *,
    cwd: str | None = None,
    session_id: str | None = None,
    stream: bool | None = None,
    auto_confirm: bool | None = None,
    confirm_callback: Callable[[str, str], bool] | None = None,
) -> AgentConfig:
    """
    AgentConfig efectivo para una ejecución (CLI, UI o scripts).

    Los kwargs permiten que cada superficie sobrescriba solo lo que le aplica
    (p. ej. la UI pasa stream/auto_confirm por petición); el resto sale de la
    config runtime. El snapshot se calcula una sola vez sobre el config final.
    """
    from ci2lab.harness.run_logger import build_config_snapshot

    effective_cwd = cwd or runtime.workspace or os.getcwd()
    agent = AgentConfig(
        cwd=effective_cwd,
        max_rounds=runtime.max_rounds,
        auto_confirm=runtime.auto_confirm if auto_confirm is None else auto_confirm,
        stream=runtime.stream if stream is None else stream,
        session_id=session_id,
        run_log_enabled=runtime.log_runs,
        runs_dir=runtime.runs_dir,
        write_tools_enabled=runtime.write_tools_enabled,
        require_diff_preview=runtime.require_diff_preview,
        confirm_callback=confirm_callback,
    )
    agent.config_snapshot = build_config_snapshot(
        runtime_fields={
            "model": selection.ollama_tag,
            "backend_url": runtime.backend_url,
            "tool_mode": selection.tool_mode,
            "workspace": effective_cwd,
        },
        agent_config=agent,
        selection=selection,
    )
    return agent
