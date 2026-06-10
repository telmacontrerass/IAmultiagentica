"""
Pipeline de preparación: hardware + selección de modelo para el arnés.

El router (models recommend) sugiere modelos; el usuario elige cuál ejecutar.
Al arrancar chat/agent se aplica el tool_mode del catálogo para ese modelo.
"""

from __future__ import annotations

import os

from ci2lab.config import DEFAULT_MODEL
from ci2lab.contracts.types import HardwareProfile, ModelSelection
from ci2lab.hardware import scan_hardware
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
