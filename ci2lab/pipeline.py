"""
Pipeline de preparación: hardware + router + runtime.

Cuando el router no está implementado, devuelve un ModelSelection por defecto.
"""

from __future__ import annotations

import os

from ci2lab.contracts.types import HardwareProfile, ModelSelection
from ci2lab.harness import default_selection
from ci2lab.router.catalog import resolve_catalog_model


def _fallback_selection(
    model_name: str,
    *,
    tool_mode: str,
) -> ModelSelection:
    model = resolve_catalog_model(model_name)
    if model:
        return ModelSelection(
            model_id=model.id,
            ollama_tag=model.ollama_tag,
            display_name=model.display_name,
            tool_mode=model.tool_mode,
            supports_tools=model.supports_tools,
            context_length=model.context_length,
        )
    return default_selection(model_name, tool_mode=tool_mode)


def prepare_session(
    user_prompt: str,
    *,
    force_model: str | None = None,
    tool_mode: str = "native",
    backend_url: str | None = None,
    pull: bool = True,  # noqa: ARG001 — usado cuando exista runtime.ensure
) -> tuple[HardwareProfile | None, ModelSelection]:
    """
    Punto de integración router ↔ arnés.

    1. Intenta scan_hardware + resolve_model (módulos del router).
    2. Si no existen, usa default_selection con --model o CI2LAB_MODEL.
    3. Cuando exista runtime.ensure_model_ready, lo invocará aquí.
    """
    _ = user_prompt

    try:
        from ci2lab.hardware.profiler import scan_hardware
        from ci2lab.router.resolve import resolve_model
        from ci2lab.runtime.ensure import ensure_model_ready

        profile = scan_hardware()
        selection = resolve_model(user_prompt, profile=profile, force_model_id=force_model)
        if pull:
            ensure_model_ready(selection)
        return profile, selection
    except ImportError:
        model_name = force_model or os.environ.get("CI2LAB_MODEL", "llama3.1:8b")
        selection = _fallback_selection(model_name, tool_mode=tool_mode)
        if backend_url:
            selection.backend_url = backend_url
        return None, selection
