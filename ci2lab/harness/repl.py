"""Modo interactivo REPL del arnés."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import LLMError
from ci2lab.harness.loop import run_agent
from ci2lab.harness.session import load_session, new_session_id, save_session
from ci2lab.harness.types import AgentConfig

console = Console()


def run_repl(
    selection: ModelSelection,
    config: AgentConfig,
    *,
    session_id: str | None = None,
) -> None:
    sid = session_id or new_session_id()
    config.session_id = sid

    history = None
    if session_id:
        data = load_session(session_id)
        if data:
            history = data.get("messages")
            console.print(f"[dim]Reanudando sesión {session_id}[/dim]")

    console.print(Panel(
        f"[bold]ci2lab REPL[/bold]\n"
        f"Modelo: {selection.ollama_tag}\n"
        f"Tool mode: {selection.tool_mode}\n"
        f"CWD: {config.cwd}\n"
        f"Sesión: {sid}\n\n"
        "Escribe tu petición. Comandos: [bold]/exit[/bold], [bold]/save[/bold], [bold]/clear[/bold]",
        title="Agente local",
        border_style="blue",
    ))

    while True:
        try:
            line = console.input("\n[bold]Tú>[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Hasta luego.[/dim]")
            break

        if not line:
            continue
        if line.lower() in {"/exit", "/quit", "exit", "quit"}:
            break
        if line.lower() == "/clear":
            history = [
                {"role": "system", "content": history[0]["content"]}
            ] if history and history[0].get("role") == "system" else None
            console.print("[dim]Historial limpiado (system conservado).[/dim]")
            continue
        if line.lower() == "/save":
            if history:
                path = save_session(sid, messages=history, model_tag=selection.ollama_tag, cwd=config.cwd)
                console.print(f"[green]Guardado en {path}[/green]")
            else:
                console.print("[yellow]Nada que guardar aún.[/yellow]")
            continue

        try:
            if history is None:
                run_agent(line, selection, config=config)
            else:
                run_agent(line, selection, config=config, messages=history)
        except LLMError as exc:
            console.print(f"[red]{exc.user_message}[/red]")
            continue

        data = load_session(sid)
        if data:
            history = data.get("messages")
