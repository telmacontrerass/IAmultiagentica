"""Modo interactivo REPL del arnés."""

from __future__ import annotations

from rich.panel import Panel

from ci2lab.console import console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import LLMError
from ci2lab.harness.query.loop import run_agent
from ci2lab.harness.session import (
    delete_session,
    is_delete_session_request,
    list_sessions,
    load_session,
    new_session_id,
    save_session,
)
from ci2lab.harness.terminal_input import read_prompt_line
from ci2lab.harness.skills.loader import load_skills
from ci2lab.harness.tools.skill_tool import invoke_skill_for_repl
from ci2lab.harness.types import AgentConfig


def run_repl(
    selection: ModelSelection,
    config: AgentConfig,
    *,
    session_id: str | None = None,
) -> None:
    sid = session_id or new_session_id()
    config.session_id = sid

    history = None
    last_user_prompt: str | None = None
    last_error_message: str | None = None
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
        "Escribe tu petición. [bold]Ctrl+V[/bold] pega; [bold]Enter[/bold] envía; "
        "[bold]Alt+Enter[/bold] nueva línea.\n"
        "Comandos: [bold]/exit[/bold], [bold]/save[/bold], [bold]/clear[/bold], "
        "[bold]/delete[/bold], [bold]/sessions[/bold], [bold]/resume ID[/bold], "
        "[bold]/retry[/bold], [bold]/why[/bold], "
        "[bold]/skills[/bold], [bold]/skill-name[/bold]",
        title="Agente local",
        border_style="blue",
    ))

    while True:
        try:
            line = read_prompt_line("Tú> ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Hasta luego.[/dim]")
            break

        if not line:
            continue
        if line.lower() in {"/exit", "/quit", "exit", "quit"}:
            break
        if line.lower() == "/sessions":
            rows = list_sessions()
            if not rows:
                console.print("[dim]No hay sesiones guardadas.[/dim]")
            else:
                for row in rows[:20]:
                    console.print(
                        f"- [bold]{row['id']}[/bold] · {row['model']} · "
                        f"{row['updated_at'][:19]} · {row['cwd']}"
                    )
            continue
        if line.lower().startswith("/resume "):
            target = line.split(maxsplit=1)[1].strip()
            if not target:
                console.print("[yellow]Uso: /resume <session_id>[/yellow]")
                continue
            data = load_session(target)
            if not data:
                console.print(f"[yellow]No existe la sesión {target}.[/yellow]")
                continue
            sid = target
            config.session_id = sid
            history = data.get("messages")
            console.print(f"[green]Sesión {sid} cargada.[/green]")
            continue
        if line.lower() == "/retry":
            if not last_user_prompt:
                console.print("[yellow]No hay petición anterior para reintentar.[/yellow]")
                continue
            line = last_user_prompt
            console.print(f"[dim]Reintentando: {line}[/dim]")
        if line.lower() == "/why":
            if not last_error_message:
                console.print("[dim]No hay fallo reciente registrado.[/dim]")
            else:
                console.print(
                    "[yellow]Último error:[/yellow]\n"
                    f"{last_error_message}\n\n"
                    "[dim]Siguiente paso: corrige el problema y usa /retry "
                    "o ejecuta `ci2lab doctor`.[/dim]"
                )
            continue
        if line.lower() == "/clear":
            history = [
                {"role": "system", "content": history[0]["content"]}
            ] if history and history[0].get("role") == "system" else None
            console.print("[dim]Historial limpiado (system conservado).[/dim]")
            continue
        if line.lower() == "/save":
            if history:
                path = save_session(
                    sid,
                    messages=history,
                    model_tag=selection.ollama_tag,
                    cwd=config.cwd,
                    token_usage=config.token_usage.to_dict(),
                )
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
            if skill_line and not skill_line.lower().startswith(
                ("exit", "quit", "save", "clear", "delete", "forget")
            ):
                parts = skill_line.split(maxsplit=1)
                skill_name = parts[0]
                skill_args = parts[1] if len(parts) > 1 else ""
                skills = load_skills(config.cwd)
                if skill_name in skills:
                    config.skill_allowed_tools = None
                    body = invoke_skill_for_repl(config, skill_name, skill_args)
                    user_request = skill_args.strip()
                    if (
                        user_request.startswith("http://")
                        or user_request.startswith("https://")
                    ) and " " not in user_request:
                        user_request = f"URL: {user_request}"
                    prompt = (
                        f"{body}\n\n---\nUser request: "
                        f"{user_request or '(use skill instructions above)'}"
                    )
                    try:
                        last_user_prompt = line
                        run_agent(prompt, selection, config=config, messages=history)
                        last_error_message = None
                    except LLMError as exc:
                        console.print(f"[red]{exc.user_message}[/red]")
                        last_error_message = exc.user_message
                        continue
                    data = load_session(sid)
                    if data:
                        history = data.get("messages")
                    continue

        try:
            config.skill_allowed_tools = None
            last_user_prompt = line
            if history is None:
                run_agent(line, selection, config=config)
            else:
                run_agent(line, selection, config=config, messages=history)
            last_error_message = None
        except LLMError as exc:
            console.print(f"[red]{exc.user_message}[/red]")
            last_error_message = exc.user_message
            continue

        data = load_session(sid)
        if data:
            history = data.get("messages")
