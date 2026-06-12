"""Modo interactivo REPL del arnés."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import LLMError
from ci2lab.harness.loop import run_agent
from ci2lab.harness.session import (
    delete_session,
    is_delete_session_request,
    load_session,
    new_session_id,
    save_session,
)
from ci2lab.harness.skills.loader import load_skills
from ci2lab.harness.tools.skill_tool import invoke_skill_for_repl
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
        "Escribe tu petición. Comandos: [bold]/exit[/bold], [bold]/save[/bold], "
        "[bold]/clear[/bold], [bold]/delete[/bold], [bold]/skills[/bold], [bold]/skill-name[/bold]",
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
        if is_delete_session_request(line):
            deleted = delete_session(sid)
            history = None
            if deleted:
                console.print(f"[green]Sesión {sid} eliminada.[/green]")
            else:
                console.print("[yellow]No había sesión guardada que eliminar.[/yellow]")
            continue
        if line.lower() == "/skills":
            skills = load_skills(config.cwd)
            if not skills:
                console.print("[dim]No skills found in .ci2lab/skills/ or ~/.ci2lab/skills/[/dim]")
            else:
                for name in sorted(skills):
                    skill = skills[name]
                    src = skill.source
                    console.print(f"- [bold]{name}[/bold] ({src}): {skill.description}")
            continue
        if line.startswith("/"):
            skill_line = line[1:].strip()
            if skill_line and not skill_line.lower().startswith(("exit", "quit", "save", "clear", "delete", "forget")):
                parts = skill_line.split(maxsplit=1)
                skill_name = parts[0]
                skill_args = parts[1] if len(parts) > 1 else ""
                skills = load_skills(config.cwd)
                if skill_name in skills:
                    config.skill_allowed_tools = None
                    body = invoke_skill_for_repl(config, skill_name, skill_args)
                    prompt = f"{body}\n\n---\nUser request: {skill_args or '(use skill instructions above)'}"
                    try:
                        run_agent(prompt, selection, config=config, messages=history)
                    except LLMError as exc:
                        console.print(f"[red]{exc.user_message}[/red]")
                        continue
                    data = load_session(sid)
                    if data:
                        history = data.get("messages")
                    continue

        try:
            config.skill_allowed_tools = None
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
