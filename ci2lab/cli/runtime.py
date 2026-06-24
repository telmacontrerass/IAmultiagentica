"""Runtime config resolution and delegation to pipeline.build_agent_config."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from ci2lab.config import DEFAULT_TOOL_MODE, Ci2LabConfig, load_config, merge_cli_config
from ci2lab.console import console
from ci2lab.harness.security_profiles import SecurityConfig
from ci2lab.harness.tools.filesystem_parts.documents import pdf_needs_vision


def _resolve_runtime_config(args: argparse.Namespace) -> Ci2LabConfig:
    base = load_config()
    merged = merge_cli_config(
        base,
        model=args.model,
        tool_mode=args.tool_mode,
        max_rounds=args.max_rounds,
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
    selection,
):
    import os
    from pathlib import Path

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
        vision_model=tool_settings.vision_model or "",
        vision_enabled=tool_settings.vision_enabled if tool_settings.vision_enabled is not None else True,
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
):
    from ci2lab.pipeline import prepare_session

    _, selection = prepare_session(
        prompt,
        force_model=runtime.model,
        tool_mode_override=_tool_mode_override(runtime, args),
        backend_url=runtime.backend_url,
        pull=False,
    )
    return selection
