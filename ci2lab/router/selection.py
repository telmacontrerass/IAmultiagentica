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
    catalog_ctx = spec.context_length if spec is not None else None
    context_length = _resolve_context_length(catalog_ctx)

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
            context_length=context_length,
            hardware_tier=profile.hardware_tier,
            reason=f"Catalog entry: tool_mode={spec.tool_mode}.",
        )

    selection = ModelSelection(
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
    if context_length is not None:
        selection.context_length = context_length
    return selection


def _resolve_context_length(catalog_context_length: int | None) -> int | None:
    """Effective context window: the model's catalog value, optionally overridden.

    This value is sent to Ollama as `num_ctx` *and* used by the harness for
    compaction, so the two always agree. `CI2LAB_NUM_CTX` lets the user cap it
    (KV-cache memory grows with the window) without editing the catalog, or
    raise it for a model whose true window exceeds the catalog entry.
    """
    override = os.environ.get("CI2LAB_NUM_CTX")
    if override:
        try:
            value = int(override.strip())
        except ValueError:
            value = 0
        if value > 0:
            return value
    return catalog_context_length


def _resolve_tool_mode(
    spec: ModelSpec | None,
    tool_mode_override: str | None,
) -> ToolMode:
    if tool_mode_override is not None:
        return tool_mode_override  # type: ignore[return-value]
    if spec is not None:
        return spec.tool_mode
    return "fenced"
