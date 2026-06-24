"""agent and chat commands."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from ci2lab.console import console
from ci2lab.cli.runtime import _build_config, _resolve_selection
from ci2lab.config import Ci2LabConfig


def _looks_like_ci2lab_repo(path: str) -> bool:
    root = Path(path).resolve()
    return (root / "ci2lab").is_dir() and (root / "pyproject.toml").is_file()


def _workspace_startup_hint(args: argparse.Namespace, cwd: str) -> None:
    if args.workspace or args.cwd:
        return
    if os.environ.get("CI2LAB_WORKSPACE_HINT"):
        return
    if _looks_like_ci2lab_repo(cwd):
        console.print(
            "[dim]Tip: to work on another project use `--workspace <path>` "
            "or set `CI2LAB_WORKSPACE_HINT`.[/dim]"
        )


def _run_turn(prompt: str, args: argparse.Namespace, runtime: Ci2LabConfig) -> int:
    from ci2lab.harness import run_agent
    from ci2lab.harness.llm_errors import LLMError
    from ci2lab.harness.session import load_session

    selection = _resolve_selection(runtime, prompt, args)
    config = _build_config(runtime, args, selection)
    history = None
    if args.session:
        data = load_session(args.session)
        if data:
            history = data.get("messages")
            console.print(f"[dim]Resuming session {args.session}[/dim]")
        else:
            console.print(
                f"[yellow]Session {args.session} not found; a new one will be started.[/yellow]"
            )

    console.print(f"[bold]Model:[/bold] {selection.ollama_tag}")
    console.print(f"[bold]Tool mode:[/bold] {selection.tool_mode}")
    console.print(f"[bold]CWD:[/bold] {config.cwd}\n")

    if config.image_paths:
        from ci2lab.harness.vision import is_vision_model
        n = len(config.image_paths)
        label = "image" if n == 1 else "images"
        console.print(f"[bold]Images:[/bold] {n} {label} attached")
        if not is_vision_model(selection.ollama_tag) and not config.vision_model:
            console.print(
                "[yellow]Warning:[/yellow] the selected model is not vision-capable "
                "and no vision_model fallback is configured. "
                "Images will be ignored.\n"
                "[dim]Tip: use a vision model (e.g. --model qwen2.5vl:7b) "
                "or set vision_model in ~/.ci2lab/settings.json.[/dim]"
            )

    _workspace_startup_hint(args, config.cwd)

    try:
        if getattr(args, "multi_agent", False):
            from ci2lab.harness.multiagent import run_multi_agent

            final_text = run_multi_agent(prompt, selection, config=config)
            if final_text:
                console.print(final_text)
        else:
            run_agent(prompt, selection, config=config, messages=history)
    except LLMError as exc:
        console.print(f"[red]{exc.user_message}[/red]")
        console.print(
            "[dim]Next step: fix the problem and retry with the same "
            "command. You can validate the environment with `ci2lab doctor`.[/dim]"
        )
        return exc.exit_code
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130
    return 0


def _run_repl(args: argparse.Namespace, runtime: Ci2LabConfig) -> int:
    from ci2lab.harness.llm_errors import LLMError
    from ci2lab.harness.repl import run_repl

    selection = _resolve_selection(runtime, "", args)
    config = _build_config(runtime, args, selection)
    _workspace_startup_hint(args, config.cwd)
    try:
        run_repl(
            selection,
            config,
            session_id=args.session,
            multi_agent=getattr(args, "multi_agent", False),
        )
    except LLMError as exc:
        console.print(f"[red]{exc.user_message}[/red]")
        console.print(
            "[dim]Next step: fix the problem and relaunch `ci2lab chat` "
            "or validate the environment with `ci2lab doctor`.[/dim]"
        )
        return exc.exit_code
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130
    return 0
