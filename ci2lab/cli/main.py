"""Punto de entrada y despacho de comandos CLI."""

from __future__ import annotations

import sys

from ci2lab.cli.commands.agent import _run_repl, _run_turn
from ci2lab.cli.commands.doctor import _cmd_doctor
from ci2lab.cli.commands.evals import _cmd_evals
from ci2lab.cli.commands.hardware import _cmd_hardware
from ci2lab.cli.commands.models import (
    _cmd_models_install,
    _cmd_models_recommend,
    _cmd_models_run,
)
from ci2lab.cli.commands.sessions import _cmd_sessions
from ci2lab.cli.commands.ui import _cmd_ui
from ci2lab.cli.parser import (
    _CLI_COMMANDS,
    _is_global_help_request,
    _print_global_help,
    build_parser,
)
from ci2lab.cli.runtime import _resolve_runtime_config


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if not raw_argv:
        parser = build_parser()
        args = parser.parse_args(raw_argv)
        try:
            runtime = _resolve_runtime_config(args)
        except ValueError as exc:
            parser.error(str(exc))
        if sys.stdin.isatty():
            from ci2lab.cli.menu import run_start_menu

            return run_start_menu(runtime)
        _print_global_help()
        return 0

    if _is_global_help_request(raw_argv):
        _print_global_help()
        return 0

    raw_argv = _expand_tools_shortcut(raw_argv)

    if raw_argv and not any(tok in _CLI_COMMANDS for tok in raw_argv):
        raw_argv = ["agent", *raw_argv]

    parser = build_parser()
    args = parser.parse_args(raw_argv)

    try:
        runtime = _resolve_runtime_config(args)
    except ValueError as exc:
        parser.error(str(exc))

    if (
        args.command == "agent"
        and getattr(args, "multi_agent", False)
        and args.agent_prompt == "chat"
    ):
        return _run_repl(args, runtime)
    if args.command == "agent":
        return _run_turn(args.agent_prompt, args, runtime)
    if args.command == "chat":
        return _run_repl(args, runtime)
    if args.command == "menu":
        from ci2lab.cli.menu import run_start_menu

        return run_start_menu(runtime)
    if args.command == "sessions":
        return _cmd_sessions(args)
    if args.command == "doctor":
        return _cmd_doctor(runtime)
    if args.command == "hardware":
        return _cmd_hardware(args)
    if args.command == "models" and args.models_command == "recommend":
        return _cmd_models_recommend(args)
    if args.command == "models" and args.models_command == "install":
        return _cmd_models_install(args)
    if args.command == "models" and args.models_command == "run":
        return _cmd_models_run(args)
    if args.command == "evals":
        return _cmd_evals(args)
    if args.command == "permissions":
        from ci2lab.cli_permissions import cmd_permissions

        return cmd_permissions(args)
    if args.command == "ui":
        return _cmd_ui(args, runtime)

    parser.print_help()
    return 0


def _expand_tools_shortcut(raw_argv: list[str]) -> list[str]:
    """Expand friendly tools shortcuts into normal agent/chat invocations."""
    if not raw_argv:
        return raw_argv
    if raw_argv[0] == "tools":
        if any(arg in {"--help", "-h"} for arg in raw_argv[1:]):
            return ["--help"]
        model: str | None = None
        rest = raw_argv[1:]
        if rest and not rest[0].startswith("-"):
            model = rest[0]
            rest = rest[1:]
        return _tools_args(model, rest)
    if len(raw_argv) >= 2 and raw_argv[1] == "tools" and not raw_argv[0].startswith("-"):
        return _tools_args(raw_argv[0], raw_argv[2:])
    return raw_argv


def _tools_args(model: str | None, rest: list[str]) -> list[str]:
    args: list[str] = []
    if model:
        args.extend(["--model", model])
    args.extend(["--tool-mode", "fenced", "--no-stream"])
    if rest:
        args.extend(["agent", " ".join(rest)])
    else:
        args.append("chat")
    return args
