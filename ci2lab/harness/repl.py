"""Interactive REPL mode for the harness."""

from __future__ import annotations

from rich.panel import Panel

from ci2lab.console import active_progress, console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import LLMError
from ci2lab.harness.multiagent import run_multi_agent
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


class _TransientProgress:
    """Render one replaceable status line and remove it when work finishes."""

    def __init__(self) -> None:
        self._status = None

    def update(self, label: str) -> None:
        if not label:
            self.clear()
            return
        rendered = f"[dim italic cyan]{label}[/dim italic cyan]"
        if self._status is None:
            self._status = console.status(rendered, spinner="dots")
            self._status.start()
            # Let interactive prompts (e.g. permission requests) pause the
            # spinner while they read input, otherwise it hides the prompt.
            active_progress.set(self._status)
        else:
            self._status.update(rendered)

    def clear(self) -> None:
        if self._status is not None:
            active_progress.clear(self._status)
            self._status.stop()
            self._status = None


def run_repl(
    selection: ModelSelection,
    config: AgentConfig,
    *,
    session_id: str | None = None,
    multi_agent: bool = False,
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
            console.print(f"[dim]Resuming session {session_id}[/dim]")

    console.print(Panel(
        f"[bold]ci2lab REPL[/bold]\n"
        f"Model: {selection.ollama_tag}\n"
        f"Tool mode: {selection.tool_mode}\n"
        f"Mode: {'multi-agent' if multi_agent else 'classic'}\n"
        f"CWD: {config.cwd}\n"
        f"Session: {sid}\n\n"
        "Type your request. [bold]Ctrl+V[/bold] pastes; [bold]Enter[/bold] sends; "
        "[bold]Alt+Enter[/bold] new line.\n"
        "Commands: [bold]/exit[/bold], [bold]/save[/bold], [bold]/clear[/bold], "
        "[bold]/delete[/bold], [bold]/sessions[/bold], [bold]/resume ID[/bold], "
        "[bold]/retry[/bold], [bold]/why[/bold], "
        "[bold]/skills[/bold], [bold]/skill-name[/bold]",
        title="Local agent",
        border_style="blue",
    ))

    while True:
        try:
            line = read_prompt_line("You> ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]See you later.[/dim]")
            break

        if not line:
            continue
        if line.lower() in {"/exit", "/quit", "exit", "quit"}:
            break
        if line.lower() == "/sessions":
            rows = list_sessions()
            if not rows:
                console.print("[dim]No saved sessions.[/dim]")
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
                console.print("[yellow]Usage: /resume <session_id>[/yellow]")
                continue
            data = load_session(target)
            if not data:
                console.print(f"[yellow]Session {target} does not exist.[/yellow]")
                continue
            sid = target
            config.session_id = sid
            history = data.get("messages")
            console.print(f"[green]Session {sid} loaded.[/green]")
            continue
        if line.lower() == "/retry":
            if not last_user_prompt:
                console.print("[yellow]No previous request to retry.[/yellow]")
                continue
            line = last_user_prompt
            console.print(f"[dim]Retrying: {line}[/dim]")
        if line.lower() == "/why":
            if not last_error_message:
                console.print("[dim]No recent failure recorded.[/dim]")
            else:
                console.print(
                    "[yellow]Last error:[/yellow]\n"
                    f"{last_error_message}\n\n"
                    "[dim]Next step: fix the problem and use /retry "
                    "or run `ci2lab doctor`.[/dim]"
                )
            continue
        if line.lower() == "/clear":
            history = [
                {"role": "system", "content": history[0]["content"]}
            ] if history and history[0].get("role") == "system" else None
            console.print("[dim]History cleared (system kept).[/dim]")
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
                console.print(f"[green]Saved to {path}[/green]")
            else:
                console.print("[yellow]Nothing to save yet.[/yellow]")
            continue
        if is_delete_session_request(line):
            deleted = delete_session(sid)
            history = None
            if deleted:
                console.print(f"[green]Session {sid} deleted.[/green]")
            else:
                console.print("[yellow]There was no saved session to delete.[/yellow]")
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
                    progress = _TransientProgress()
                    try:
                        last_user_prompt = line
                        if multi_agent:
                            final_text = run_multi_agent(
                                prompt,
                                selection,
                                config=config,
                                on_progress=progress.update,
                            )
                            if final_text:
                                console.print(final_text)
                                history = (history or []) + [
                                    {"role": "user", "content": prompt},
                                    {"role": "assistant", "content": final_text},
                                ]
                                save_session(
                                    sid,
                                    messages=history,
                                    model_tag=selection.ollama_tag,
                                    cwd=config.cwd,
                                    token_usage=config.token_usage.to_dict(),
                                )
                        else:
                            run_agent(
                                prompt,
                                selection,
                                config=config,
                                messages=history,
                                on_progress=progress.update,
                            )
                        last_error_message = None
                    except LLMError as exc:
                        console.print(f"[red]{exc.user_message}[/red]")
                        last_error_message = exc.user_message
                        continue
                    finally:
                        progress.clear()
                    data = load_session(sid)
                    if data:
                        history = data.get("messages")
                    continue

        progress = _TransientProgress()
        try:
            config.skill_allowed_tools = None
            last_user_prompt = line
            if multi_agent:
                final_text = run_multi_agent(
                    line,
                    selection,
                    config=config,
                    on_progress=progress.update,
                )
                if final_text:
                    console.print(final_text)
                    history = (history or []) + [
                        {"role": "user", "content": line},
                        {"role": "assistant", "content": final_text},
                    ]
                    save_session(
                        sid,
                        messages=history,
                        model_tag=selection.ollama_tag,
                        cwd=config.cwd,
                        token_usage=config.token_usage.to_dict(),
                    )
            elif history is None:
                run_agent(
                    line,
                    selection,
                    config=config,
                    on_progress=progress.update,
                )
            else:
                run_agent(
                    line,
                    selection,
                    config=config,
                    messages=history,
                    on_progress=progress.update,
                )
            last_error_message = None
        except LLMError as exc:
            console.print(f"[red]{exc.user_message}[/red]")
            last_error_message = exc.user_message
            continue
        finally:
            progress.clear()

        data = load_session(sid)
        if data:
            history = data.get("messages")
