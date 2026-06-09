"""CLI principal de Ci2Lab."""

from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console
from rich.table import Table

console = Console()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ci2lab",
        description="Agente local multi-modelo con arnés agéntico",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Petición directa (atajo: ci2lab \"tu tarea\")",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Tag Ollama (override; si no, router o CI2LAB_MODEL)",
    )
    parser.add_argument(
        "--tool-mode",
        choices=["native", "fenced"],
        default="native",
    )
    parser.add_argument("--cwd", default=None, help="Directorio de trabajo")
    parser.add_argument("--yes", action="store_true", help="Auto-confirmar tools peligrosas")
    parser.add_argument("--no-stream", action="store_true", help="Desactivar streaming de tokens")
    parser.add_argument("--max-rounds", type=int, default=25)
    parser.add_argument("--session", default=None, help="ID de sesión (nueva si se omite en REPL)")

    sub = parser.add_subparsers(dest="command")

    agent_p = sub.add_parser("agent", help="Una petición y salir")
    agent_p.add_argument("agent_prompt", help="Petición para el agente")
    _add_agent_flags(agent_p)

    sub.add_parser("chat", help="Modo interactivo REPL").set_defaults(command="chat")

    sessions_p = sub.add_parser("sessions", help="Listar sesiones guardadas")
    sessions_p.add_argument("--json", action="store_true")

    sub.add_parser("doctor", help="Comprobar entorno")

    args = parser.parse_args(argv)
    args.cwd = os.path.abspath(args.cwd or os.getcwd())

    if args.command == "agent":
        return _run_turn(args.agent_prompt, args)
    if args.command == "chat":
        return _run_repl(args)
    if args.command == "sessions":
        return _cmd_sessions(args)
    if args.command == "doctor":
        return _cmd_doctor()
    if args.prompt:
        return _run_turn(args.prompt, args)

    parser.print_help()
    return 0


def _add_agent_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", default=None)
    p.add_argument("--tool-mode", choices=["native", "fenced"], default="native")
    p.add_argument("--cwd", default=None)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-stream", action="store_true")
    p.add_argument("--max-rounds", type=int, default=25)
    p.add_argument("--session", default=None)


def _build_config(args: argparse.Namespace):
    from ci2lab.harness import AgentConfig

    return AgentConfig(
        cwd=args.cwd,
        max_rounds=args.max_rounds,
        auto_confirm=args.yes,
        stream=not args.no_stream,
        session_id=args.session,
    )


def _resolve_selection(args: argparse.Namespace, prompt: str):
    from ci2lab.pipeline import prepare_session

    _, selection = prepare_session(
        prompt,
        force_model=args.model,
        tool_mode=args.tool_mode,
        pull=False,
    )
    return selection


def _run_turn(prompt: str, args: argparse.Namespace) -> int:
    from ci2lab.harness import run_agent

    selection = _resolve_selection(args, prompt)
    config = _build_config(args)

    console.print(f"[bold]Modelo:[/bold] {selection.ollama_tag}")
    console.print(f"[bold]CWD:[/bold] {config.cwd}\n")

    try:
        run_agent(prompt, selection, config=config)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido.[/yellow]")
        return 130
    return 0


def _run_repl(args: argparse.Namespace) -> int:
    from ci2lab.harness.repl import run_repl

    selection = _resolve_selection(args, "")
    config = _build_config(args)
    try:
        run_repl(selection, config, session_id=args.session)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido.[/yellow]")
        return 130
    return 0


def _cmd_sessions(args: argparse.Namespace) -> int:
    import json

    from ci2lab.harness.session import list_sessions

    rows = list_sessions()
    if args.json:
        console.print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        console.print("No hay sesiones guardadas.")
        return 0
    table = Table(title="Sesiones ~/.ci2lab/sessions")
    table.add_column("ID")
    table.add_column("Modelo")
    table.add_column("CWD")
    table.add_column("Actualizado")
    for row in rows:
        table.add_row(row["id"], row["model"], row["cwd"][:40], row["updated_at"][:19])
    console.print(table)
    return 0


def _cmd_doctor() -> int:
    import httpx

    ok = True
    console.print("[bold]ci2lab doctor[/bold]\n")

    try:
        import ci2lab  # noqa: F401
        console.print("[green]✓[/green] Paquete ci2lab importable")
    except ImportError as exc:
        console.print(f"[red]✗[/red] ci2lab: {exc}")
        ok = False

    url = os.environ.get("CI2LAB_OLLAMA_URL", "http://localhost:11434")
    try:
        r = httpx.get(f"{url}/api/tags", timeout=3.0)
        r.raise_for_status()
        models = [m.get("name") for m in r.json().get("models", [])]
        console.print(f"[green]✓[/green] Ollama en {url} ({len(models)} modelos)")
        if models:
            console.print(f"  Ejemplos: {', '.join(models[:5])}")
    except Exception as exc:
        console.print(f"[red]✗[/red] Ollama no responde en {url}: {exc}")
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
