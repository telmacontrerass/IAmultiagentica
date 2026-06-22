"""
Preparation pipeline: hardware + model selection for the harness.

The router (models recommend) suggests models; the user chooses which one to run.
When chat/agent starts, the catalog tool_mode for that model is applied.
"""

from __future__ import annotations

import os
from typing import Callable

from ci2lab.config import DEFAULT_MODEL, Ci2LabConfig
from ci2lab.contracts.types import HardwareProfile, ModelSelection
from ci2lab.hardware import scan_hardware
from ci2lab.harness.security_profiles import SecurityConfig
from ci2lab.harness.types import AgentConfig
from ci2lab.router.selection import build_model_selection

# A single tool result may use up to this fraction of the model's context
# window; the rest is left for the system prompt, prior turns and the model's
# own output. Sized in characters (~4 per token).
_TOOL_OUTPUT_CONTEXT_FRACTION = 0.5
_CHARS_PER_TOKEN = 4
_TOOL_OUTPUT_FLOOR = 8_000
_TOOL_OUTPUT_CAP = 200_000


def resolve_tool_output_budget(selection: ModelSelection, sec: SecurityConfig) -> int:
    """Per-call tool-output budget, scaled to the model's context window.

    The fixed 10k-char default was sized for a ~4k-token window. Now that the
    real window is loaded (Ollama `num_ctx`), that default needlessly offloaded
    normal documents to disk as a head+tail preview — hiding the middle, so the
    model could not actually read what it was asked to (it wrote placeholders).
    Scaling to the window keeps an ordinary document inline. An explicit
    `security.limits.max_tool_output_chars` still wins.
    """
    if sec.max_tool_output_chars is not None:
        return sec.max_tool_output_chars
    context_length = getattr(selection, "context_length", 0) or 0
    scaled = int(context_length * _CHARS_PER_TOKEN * _TOOL_OUTPUT_CONTEXT_FRACTION)
    return max(_TOOL_OUTPUT_FLOOR, min(scaled, _TOOL_OUTPUT_CAP))


def prepare_session(
    user_prompt: str,
    *,
    force_model: str | None = None,
    tool_mode_override: str | None = None,
    backend_url: str | None = None,
    pull: bool = True,
) -> tuple[HardwareProfile | None, ModelSelection]:
    """
    Prepares a harness session for the model the user chose.

    - Does not auto-select a model from the router (that is `ci2lab models recommend`).
    - Applies the catalog tool_mode for the chosen tag.
    - `tool_mode_override` only when the user passes --tool-mode on the CLI.
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
    image_paths: list[str] | None = None,
    tool_settings=None,
    vision_model: str = "",
    vision_enabled: bool = True,
) -> AgentConfig:
    """
    Effective AgentConfig for a single run (CLI, UI or scripts).

    The kwargs let each surface override only what applies to it (e.g. the UI
    passes stream/auto_confirm per request); the rest comes from the runtime
    config. The snapshot is computed once over the final config.
    """
    from ci2lab.harness.run_logger import build_config_snapshot
    from ci2lab.harness.security_profiles import resolved_opencode_permissions

    effective_cwd = cwd or runtime.workspace or os.getcwd()
    sec = runtime.security
    limits = sec.resolved_limits()
    opencode_perms = resolved_opencode_permissions(
        sec,
        root_permission=runtime.permission or None,
    )
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
        verify_completion=runtime.verify_completion,
        confirm_callback=confirm_callback,
        security_engine=sec.engine,
        security_profile=sec.profile,
        opencode_permissions=opencode_perms,
        bash_timeout_seconds=limits.bash_timeout_seconds,
        max_tool_output_chars=resolve_tool_output_budget(selection, sec),
        tool_settings=tool_settings,
        image_paths=image_paths or [],
        vision_model=vision_model,
        vision_enabled=vision_enabled,
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
