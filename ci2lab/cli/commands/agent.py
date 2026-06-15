"""Comandos agent y chat."""

from __future__ import annotations

import argparse

from ci2lab.console import console
from ci2lab.cli.runtime import _build_config, _resolve_selection
from ci2lab.config import Ci2LabConfig


def _run_turn(prompt: str, args: argparse.Namespace, runtime: Ci2LabConfig) -> int:
    from ci2lab.harness import run_agent
    from ci2lab.harness.llm_errors import LLMError

    selection = _resolve_selection(runtime, prompt, args)
    config = _build_config(runtime, args, selection)

    console.print(f"[bold]Modelo:[/bold] {selection.ollama_tag}")
    console.print(f"[bold]Tool mode:[/bold] {selection.tool_mode}")
    console.print(f"[bold]CWD:[/bold] {config.cwd}\n")

    try:
        run_agent(prompt, selection, config=config)
    except LLMError as exc:
        console.print(f"[red]{exc.user_message}[/red]")
        return exc.exit_code
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido.[/yellow]")
        return 130
    return 0


def _run_repl(args: argparse.Namespace, runtime: Ci2LabConfig) -> int:
    from ci2lab.harness.llm_errors import LLMError
    from ci2lab.harness.repl import run_repl

    selection = _resolve_selection(runtime, "", args)
    config = _build_config(runtime, args, selection)
    try:
        run_repl(selection, config, session_id=args.session)
    except LLMError as exc:
        console.print(f"[red]{exc.user_message}[/red]")
        return exc.exit_code
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido.[/yellow]")
        return 130
    return 0
