"""Build ModelSelection from a user-chosen model tag + catalog metadata."""

from __future__ import annotations

import os
from typing import Literal

from ci2lab.contracts import HardwareProfile, ModelSelection, ModelSpec, ToolMode
from ci2lab.hardware import scan_hardware
from ci2lab.router.imported_models import ImportedModelProfile, find_imported_model_by_tag
from ci2lab.router.catalog import find_model_by_tag

# --- Context-window sizing ------------------------------------------------
# By default a model runs at its native maximum context window (the catalog
# ``context_length``). That window is loaded as Ollama's ``num_ctx`` *and* used
# by the harness for compaction, so the two must stay in agreement. The KV
# cache grows linearly with the window, so on a memory-constrained machine the
# full native window can exceed available VRAM/RAM and force a slow CPU
# offload (or fail outright). The constants below turn the model's weight
# footprint into a conservative per-token KV-cache cost so the default window
# can be trimmed to whatever the scanned hardware can actually hold.
#
# These are intentionally rough, over-estimating bias: it is safer to
# under-promise the window than to exceed memory. ``CI2LAB_NUM_CTX`` overrides
# the whole computation when the operator wants an exact value.
_KV_BYTES_PER_TOKEN_PER_WEIGHT_GB = 30_000
"""Approx. KV-cache bytes per context token, per GB of (quantized) weights.

Calibrated so a ~7B GQA model (~4.8 GB of q4 weights) costs ~0.14 MB/token,
in line with measured fp16 KV-cache footprints for grouped-query attention.
"""

_CONTEXT_SAFETY_FRACTION = 0.9
"""Fraction of free memory the KV cache is allowed to claim (leaves headroom)."""

_MIN_CONTEXT = 2048
"""Floor for an auto-sized window; below this a model is barely usable."""

_CONTEXT_ROUNDING = 1024
"""Round auto-sized windows down to this multiple for tidy, stable values."""


def build_model_selection(
    ollama_tag: str,
    *,
    tool_mode_override: str | None = None,
    context_length_override: int | None = None,
    backend: str = "ollama",
    backend_url: str | None = None,
    profile: HardwareProfile | None = None,
) -> ModelSelection:
    """Build a :class:`ModelSelection` for the model the user chose to run.

    The router recommends models; the user picks one. This applies catalog
    metadata (notably ``tool_mode`` and the native context window) for that tag
    and records which inference provider will serve it.

    Args:
        ollama_tag: The model tag to run (a catalog id, ``ollama_tag`` or
            display name).
        tool_mode_override: Forces ``native``/``fenced`` tool mode, overriding
            the catalog (set from the CLI ``--tool-mode`` flag).
        backend: Inference provider (``"ollama"`` or ``"openai"``); anything
            other than ``"ollama"`` resolves to the OpenAI-compatible transport.
        backend_url: Base URL of the inference server; falls back to the
            ``CI2LAB_BACKEND_URL`` / ``CI2LAB_OLLAMA_URL`` env vars, then the
            local Ollama default.
        profile: Pre-scanned hardware profile; scanned on demand when omitted.

    Returns:
        A fully-populated :class:`ModelSelection` the harness can run from.
    """
    imported = find_imported_model_by_tag(ollama_tag)
    spec = None if imported is not None else find_model_by_tag(ollama_tag)
    profile = profile or scan_hardware()
    tool_mode: ToolMode = _resolve_tool_mode(spec, tool_mode_override, imported=imported)
    context_length = _resolve_context_length(
        spec,
        profile,
        imported=imported,
        explicit_override=context_length_override,
    )
    provider: Literal["ollama", "openai"] = "ollama" if backend == "ollama" else "openai"

    resolved_backend: str = (
        backend_url
        or os.environ.get("CI2LAB_BACKEND_URL")
        or os.environ.get("CI2LAB_OLLAMA_URL")
        or "http://localhost:11434/v1"
    )

    if imported is not None:
        temperature = imported.parameters.get("temperature", 0.2)
        try:
            resolved_temperature = float(temperature)
        except (TypeError, ValueError):
            resolved_temperature = 0.2
        imported_backend: Literal["ollama", "openai"] = (
            "ollama" if imported.backend == "ollama" else "openai"
        )
        return ModelSelection(
            model_id=imported.id,
            ollama_tag=imported.ollama_tag,
            display_name=imported.display_name,
            backend=imported_backend,
            backend_url=resolved_backend,
            tool_mode=tool_mode,
            supports_tools=imported.supports_tools,
            context_length=context_length if context_length is not None else imported.context_length,
            hardware_tier=profile.hardware_tier,
            temperature=resolved_temperature,
            reason=(
                f"Imported model profile: template={imported.template_id}, "
                f"tool_mode={imported.tool_mode}."
            ),
        )

    if spec is not None:
        return ModelSelection(
            model_id=spec.id,
            ollama_tag=spec.ollama_tag,
            display_name=spec.display_name,
            backend=provider,
            backend_url=resolved_backend,
            tool_mode=tool_mode,
            supports_tools=spec.supports_tools,
            context_length=context_length if context_length is not None else spec.context_length,
            hardware_tier=profile.hardware_tier,
            reason=f"Catalog entry: tool_mode={spec.tool_mode}.",
        )

    selection = ModelSelection(
        model_id=ollama_tag.replace(":", "-"),
        ollama_tag=ollama_tag,
        display_name=ollama_tag,
        backend=provider,
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


def _resolve_context_length(
    spec: ModelSpec | None,
    profile: HardwareProfile | None,
    *,
    imported: ImportedModelProfile | None = None,
    explicit_override: int | None = None,
) -> int | None:
    """Resolve the effective context window for a model selection.

    Resolution order, highest precedence first:

    1. ``CI2LAB_NUM_CTX`` — an explicit operator override, used verbatim.
    2. The model's native maximum window (catalog ``context_length``), trimmed
       to what ``profile`` can hold in memory (see :func:`_fit_context_to_hardware`).
    3. ``None`` for an unknown model with no override (the caller keeps the
       :class:`~ci2lab.contracts.types.ModelSelection` default).

    The returned value is sent to Ollama as ``num_ctx`` *and* drives the
    harness compaction math, so a single resolved number keeps the two in
    agreement.

    Args:
        spec: Catalog entry for the chosen model, or ``None`` when the tag is
            not in the catalog.
        profile: Scanned hardware profile used to size the window, or ``None``
            to skip the hardware cap.

    Returns:
        The effective context window in tokens, or ``None`` when no catalog
        entry and no override apply.
    """
    if explicit_override is not None and explicit_override > 0:
        return explicit_override
    override = _env_num_ctx_override()
    if override is not None:
        return override
    if imported is not None:
        return imported.context_length
    if spec is None:
        return None
    return _fit_context_to_hardware(spec, profile)


def _env_num_ctx_override() -> int | None:
    """Return a positive ``CI2LAB_NUM_CTX`` override, or ``None`` if unset/invalid.

    ``CI2LAB_NUM_CTX`` lets an operator pin an exact window — to cap KV-cache
    memory below the auto-sized value, or to raise it past the catalog entry
    for a model whose real window exceeds it.
    """
    raw = os.environ.get("CI2LAB_NUM_CTX")
    if not raw:
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _fit_context_to_hardware(
    spec: ModelSpec,
    profile: HardwareProfile | None,
) -> int:
    """Trim a model's native context window to what the hardware can hold.

    Each model defaults to its native maximum window. The KV cache for that
    window must fit in the memory left over after the model's weights, so this
    estimates the largest window the scanned memory budget affords and returns
    ``min(native_max, affordable)``.

    When the model's weights already exceed the inference budget the model
    cannot fit regardless of window size (Ollama will offload it either way),
    so the native window is returned unchanged rather than reported as tiny.

    Args:
        spec: Catalog entry for the chosen model.
        profile: Scanned hardware profile, or ``None`` to skip the cap.

    Returns:
        The context window in tokens, never below :data:`_MIN_CONTEXT` and
        never above the model's native maximum.
    """
    native_max = spec.context_length
    if profile is None or native_max <= _MIN_CONTEXT:
        return native_max

    weights_gb = spec.vram_min_gb if profile.inference_mode == "gpu" else spec.ram_inference_gb
    headroom_gb = profile.inference_budget_gb - weights_gb
    if headroom_gb <= 0:
        return native_max

    size_proxy_gb = max(spec.vram_min_gb, 0.1)
    kv_bytes_per_token = _KV_BYTES_PER_TOKEN_PER_WEIGHT_GB * size_proxy_gb
    affordable_tokens = int(
        headroom_gb * _CONTEXT_SAFETY_FRACTION * 1_000_000_000 / kv_bytes_per_token
    )
    affordable_tokens -= affordable_tokens % _CONTEXT_ROUNDING

    return max(_MIN_CONTEXT, min(native_max, affordable_tokens))


def _resolve_tool_mode(
    spec: ModelSpec | None,
    tool_mode_override: str | None,
    *,
    imported: ImportedModelProfile | None = None,
) -> ToolMode:
    if tool_mode_override is not None:
        return tool_mode_override  # type: ignore[return-value]
    if imported is not None:
        return imported.tool_mode
    if spec is not None:
        return spec.tool_mode
    return "fenced"
