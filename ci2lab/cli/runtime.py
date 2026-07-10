"""Runtime config resolution and delegation to pipeline.build_agent_config."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import TYPE_CHECKING

from ci2lab.config import DEFAULT_TOOL_MODE, Ci2LabConfig, load_config, merge_cli_config
from ci2lab.console import console
from ci2lab.harness.security_profiles import SecurityConfig
from ci2lab.harness.tools.filesystem_parts.documents import pdf_needs_vision

if TYPE_CHECKING:
    from ci2lab.contracts import ModelSelection
    from ci2lab.harness.types import AgentConfig


def _resolve_runtime_config(args: argparse.Namespace) -> Ci2LabConfig:
    """Merge CLI flags onto the loaded config and apply any security-engine override.

    Args:
        args: Parsed CLI arguments carrying the agent flags (model, tool mode,
            workspace, security engine, etc.).

    Returns:
        The effective :class:`Ci2LabConfig` after merging CLI overrides.

    Raises:
        ValueError: If ``merge_cli_config`` rejects an invalid combination of
            flags.
    """
    base = load_config()
    merged = merge_cli_config(
        base,
        model=args.model,
        backend=getattr(args, "backend", None),
        backend_url=getattr(args, "backend_url", None),
        tool_mode=args.tool_mode,
        max_rounds=args.max_rounds,
        context_length=getattr(args, "context_length", None),
        workspace=args.workspace,
        cwd=args.cwd,
        no_stream=args.no_stream,
        auto_confirm=args.yes,
        runs_dir=args.runs_dir,
        no_log=args.no_log,
    )
    if getattr(args, "security_engine", None) is not None:
        from ci2lab.security.engine import normalize_security_engine

        sec = merged.security
        engine = normalize_security_engine(args.security_engine)
        merged = Ci2LabConfig(
            **{
                **merged.__dict__,
                "security": SecurityConfig(
                    profile=sec.profile,
                    engine=engine,
                    bash_timeout_seconds=sec.bash_timeout_seconds,
                    max_tool_output_chars=sec.max_tool_output_chars,
                    permission=sec.permission,
                    permission_preset=sec.permission_preset,
                ),
            }
        )
    return merged


def _build_config(
    runtime: Ci2LabConfig,
    args: argparse.Namespace,
    selection: ModelSelection,
) -> AgentConfig:
    """Build the agent configuration for a run, resolving workspace and images.

    Resolves the effective working directory, loads tool settings for it and
    rewrites ``--image`` paths relative to that workspace (skipping text PDFs,
    which should be read via ``read_document``).

    Args:
        runtime: The merged runtime configuration.
        args: Parsed CLI arguments (workspace/cwd, session and image paths).
        selection: The resolved model selection for this run.

    Returns:
        The :class:`AgentConfig` produced by ``pipeline.build_agent_config``.
    """
    from ci2lab.pipeline import build_agent_config
    from ci2lab.settings import load_settings

    effective_cwd = (
        getattr(args, "workspace", None)
        or getattr(args, "cwd", None)
        or runtime.workspace
        or os.getcwd()
    )
    tool_settings = load_settings(effective_cwd)

    # Resolve --image paths against the effective workspace so that relative
    # paths like "--image image1.png" work from any working directory.
    # Text-based PDFs are skipped — they should be read with read_document.
    raw_images = getattr(args, "images", None) or []
    resolved_images: list[str] = []
    for p in raw_images:
        path = Path(p) if Path(p).is_absolute() else Path(effective_cwd) / p
        resolved = str(path)
        if path.suffix.lower() == ".pdf" and not pdf_needs_vision(path):
            console.print(
                f"[yellow]Skipping --image for text PDF '{path.name}'.[/yellow] "
                "[dim]Mention the file in your prompt and the agent will use "
                "read_document.[/dim]"
            )
            continue
        resolved_images.append(resolved)

    return build_agent_config(
        runtime,
        selection,
        session_id=args.session,
        image_paths=resolved_images,
        tool_settings=tool_settings,
        vision_model=tool_settings.vision_model or "qwen2.5vl:7b",
        vision_enabled=tool_settings.vision_enabled
        if tool_settings.vision_enabled is not None
        else True,
    )


def _tool_mode_override(runtime: Ci2LabConfig, args: argparse.Namespace) -> str | None:
    """CLI flag or yaml/env config override catalog; None means use catalog default."""
    if args.tool_mode is not None:
        return args.tool_mode
    if runtime.tool_mode != DEFAULT_TOOL_MODE:
        return runtime.tool_mode
    return None


def _resolve_selection(
    runtime: Ci2LabConfig,
    prompt: str,
    args: argparse.Namespace,
) -> ModelSelection:
    """Resolve the model selection for a prompt without pulling the model.

    Args:
        runtime: The merged runtime configuration (model, backend, tool mode).
        prompt: The user prompt; influences routing when no model is forced.
        args: Parsed CLI arguments used to compute the tool-mode override.

    Returns:
        The resolved :class:`ModelSelection`.
    """
    from ci2lab.pipeline import prepare_session

    _, selection = prepare_session(
        prompt,
        force_model=runtime.model,
        tool_mode_override=_tool_mode_override(runtime, args),
        backend=runtime.backend,
        backend_url=runtime.backend_url,
        context_length_override=runtime.context_length,
        pull=False,
    )
    return selection
