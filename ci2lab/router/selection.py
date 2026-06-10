"""Build ModelSelection from a user-chosen model tag + catalog metadata."""

from __future__ import annotations

import os

from ci2lab.contracts import HardwareProfile, ModelSelection, ModelSpec, ToolMode
from ci2lab.hardware import scan_hardware
from ci2lab.router.catalog import find_model_by_tag


def build_model_selection(
    ollama_tag: str,
    *,
    tool_mode_override: str | None = None,
    backend_url: str | None = None,
    profile: HardwareProfile | None = None,
) -> ModelSelection:
    """
    Build a ModelSelection for the model the user chose to run.

    The router recommends models; the user picks one. This function applies
    catalog metadata (especially tool_mode) for that tag. CLI --tool-mode
    overrides the catalog when explicitly provided.
    """
    spec = find_model_by_tag(ollama_tag)
    profile = profile or scan_hardware()
    tool_mode: ToolMode = _resolve_tool_mode(spec, tool_mode_override)

    resolved_backend = backend_url or os.environ.get(
        "CI2LAB_BACKEND_URL",
        os.environ.get("CI2LAB_OLLAMA_URL", "http://localhost:11434/v1"),
    )

    if spec is not None:
        return ModelSelection(
            model_id=spec.id,
            ollama_tag=spec.ollama_tag,
            display_name=spec.display_name,
            backend_url=resolved_backend,
            tool_mode=tool_mode,
            supports_tools=spec.supports_tools,
            context_length=spec.context_length,
            hardware_tier=profile.hardware_tier,
            reason=f"Catalog entry: tool_mode={spec.tool_mode}.",
        )

    return ModelSelection(
        model_id=ollama_tag.replace(":", "-"),
        ollama_tag=ollama_tag,
        display_name=ollama_tag,
        backend_url=resolved_backend,
        tool_mode=tool_mode,
        supports_tools=True,
        hardware_tier=profile.hardware_tier,
        reason="Model not in catalog; defaulting tool_mode to fenced.",
        warnings=["Model not in catalog; using fenced tool mode."],
    )


def _resolve_tool_mode(
    spec: ModelSpec | None,
    tool_mode_override: str | None,
) -> ToolMode:
    if tool_mode_override is not None:
        return tool_mode_override  # type: ignore[return-value]
    if spec is not None:
        return spec.tool_mode
    return "fenced"
