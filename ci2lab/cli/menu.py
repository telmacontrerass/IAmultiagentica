"""Interactive startup menu for the ci2lab CLI."""

from __future__ import annotations

import json
import os
import base64
import shlex
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ci2lab.config import Ci2LabConfig
from ci2lab.console import console
from ci2lab.hardware import scan_hardware
from ci2lab.router.catalog import load_model_catalog
from ci2lab.router.recommend import model_fits
from ci2lab.runtime.ollama import (
    fetch_installed_models,
    is_catalog_model_installed,
    ollama_install_info,
)

CommandRunner = Callable[[list[str]], int]


@dataclass(frozen=True)
class MenuOption:
    label: str
    description: str
    value: str


@dataclass(frozen=True)
class ModelChoice:
    label: str
    value: str
    ollama_tag: str
    installed: bool
    catalog_id: str | None = None
    fits: bool | None = None


WELCOME_ART = r"""        ___       ___
   ___ /   \ ___ /   \ ___
  /   \\___//   \\___//   \
  \___/  C I 2 L A B  \___/
      \___/       \___/"""

_ANSI_RESET = "\x1b[0m"
_ANSI_DIM = "\x1b[90m"
_ANSI_GOLD = "\x1b[33;1m"
_ANSI_BLUE = "\x1b[34;1m"


MAIN_OPTIONS: tuple[MenuOption, ...] = (
    MenuOption("Open web interface", "Start the local browser UI.", "ui"),
    MenuOption("Start chat with tools", "Classic ci2lab chat with the selected model.", "chat"),
    MenuOption(
        "My projects",
        "Open a project, manage its sources and continue its chats.",
        "projects",
    ),
    MenuOption(
        "Start chat with agents",
        "Sequential planner/researcher/coder/validator/reviewer flow.",
        "multi_chat",
    ),
    MenuOption(
        "Start simple tools chat",
        "Fenced tool mode and no streaming, matching `ci2lab tools`.",
        "tools_chat",
    ),
    MenuOption("Run one-shot agent task", "Write a prompt and run one agent turn.", "agent_once"),
    MenuOption("Check Ollama and environment", "Run `ci2lab doctor`.", "doctor"),
    MenuOption("Check computer hardware", "Show RAM/GPU/inference budget.", "hardware"),
    MenuOption(
        "Recommend models for this computer",
        "General download plan based on local hardware.",
        "models_recommend",
    ),
    MenuOption(
        "Recommend models for a task",
        "Describe the task and rank catalog models for it.",
        "models_recommend_task",
    ),
    MenuOption("Install/download a model", "Pick a model and run `ollama pull`.", "model_install"),
    MenuOption("Open direct Ollama chat", "Pick a model and run `ollama run`.", "ollama_run"),
    MenuOption("Sessions", "Open session JSON files or resume a saved chat.", "sessions"),
    MenuOption("Permissions dashboard", "Audit permissions and session approvals.", "permissions"),
    MenuOption("Run evals", "Run mock or live harness evaluations.", "evals"),
    MenuOption("What is ci2lab?", "Short explanation of this program.", "about"),
    MenuOption("Show command help", "Print the classic command reference.", "help"),
    MenuOption(
        "Work with commands",
        "Type and run ci2lab commands manually.",
        "command_mode",
    ),
    MenuOption("Exit", "Close this launcher.", "exit"),
)


PERMISSIONS_OPTIONS: tuple[MenuOption, ...] = (
    MenuOption("Summary", "Permissions summary for the workspace.", "summary"),
    MenuOption("Recent denied", "Recent deny/block events.", "recent-denied"),
    MenuOption("Recent asked", "Recent ask/confirmation events.", "recent-asked"),
    MenuOption("Audit tail", "Last audit events as formatted JSON lines.", "audit-tail"),
    MenuOption("Session approvals", "In-memory approvals for this process.", "session-list"),
    MenuOption("Clear session approvals", "Clear in-memory session approvals.", "session-clear"),
    MenuOption("Retry plan for event", "Show a retry plan for an event id.", "retry-plan"),
    MenuOption("Approve session event", "Grant allow_session for an event id.", "approve-session"),
    MenuOption("Back", "Return to the main menu.", "back"),
)


SESSION_OPTIONS: tuple[MenuOption, ...] = (
    MenuOption("Open session JSON", "Open the saved .json file for a session.", "open_json"),
    MenuOption("Resume session in chat", "Open classic chat with this session id.", "resume_chat"),
    MenuOption(
        "Resume session in multi-agent chat",
        "Open multi-agent chat with this session id.",
        "resume_multi_chat",
    ),
    MenuOption("List sessions in terminal", "Run `ci2lab sessions`.", "list"),
    MenuOption("Back", "Return to the main menu.", "back"),
)


EVAL_OPTIONS: tuple[MenuOption, ...] = (
    MenuOption("Run mock evals", "No Ollama needed.", "mock"),
    MenuOption("Run live evals", "Uses a selected Ollama model.", "live"),
    MenuOption("Back", "Return to the main menu.", "back"),
)


def run_start_menu(
    runtime: Ci2LabConfig,
    *,
    command_runner: CommandRunner | None = None,
) -> int:
    """Show the interactive launcher until the user exits."""
    runner = command_runner or _default_command_runner
    while True:
        selected = select_from_menu(
            "ci2lab launcher",
            MAIN_OPTIONS,
            subtitle=f"Workspace: {runtime.workspace or os.getcwd()}",
        )
        if selected is None or selected == "exit":
            console.print("[dim]Bye.[/dim]")
            return 0
        code = _handle_main_choice(selected, runtime, runner)
        if selected in {"chat", "multi_chat", "tools_chat", "ui"} and code:
            return code
        if selected != "exit":
            _pause()


def _handle_main_choice(
    selected: str,
    runtime: Ci2LabConfig,
    runner: CommandRunner,
) -> int:
    if selected == "ui":
        return _run_command(["ui"], runner)
    if selected == "chat":
        return _run_chat_command(runtime, runner, ["chat"])
    if selected == "projects":
        return _projects_menu(runtime)
    if selected == "multi_chat":
        return _run_chat_command(runtime, runner, ["--multi-agent", "chat"])
    if selected == "tools_chat":
        return _run_chat_command(
            runtime,
            runner,
            ["--tool-mode", "fenced", "--no-stream", "chat"],
        )
    if selected == "agent_once":
        task = _ask_text("Task for the agent")
        if not task:
            return 0
        return _run_command(["agent", task], runner)
    if selected == "doctor":
        return _run_doctor_with_ollama_install_option(runner)
    if selected == "hardware":
        return _run_command(["hardware"], runner)
    if selected == "models_recommend":
        return _run_command(["models", "recommend"], runner)
    if selected == "models_recommend_task":
        task = _ask_text("Describe the task")
        if not task:
            return 0
        return _run_command(["models", "recommend", task], runner)
    if selected == "model_install":
        choice = select_model(runtime)
        if choice is None:
            return 0
        if choice.installed:
            console.print(f"[green]Already installed:[/green] {choice.ollama_tag}")
            return 0
        return _pull_model(choice.ollama_tag)
    if selected == "ollama_run":
        choice = select_model(runtime)
        if choice is None or not _ensure_model_installed(choice):
            return 0
        if choice.catalog_id:
            return _run_command(["models", "run", choice.catalog_id], runner)
        return _run_direct_ollama(choice.ollama_tag)
    if selected == "sessions":
        return _sessions_menu(runner)
    if selected == "permissions":
        return _permissions_menu(runner)
    if selected == "evals":
        return _evals_menu(runtime, runner)
    if selected == "about":
        _print_about()
        return 0
    if selected == "help":
        return _run_command(["--help"], runner)
    if selected == "command_mode":
        return _command_mode(runner)
    return 0


def _run_chat_command(
    runtime: Ci2LabConfig,
    runner: CommandRunner,
    base_args: list[str],
) -> int:
    choice = select_model(runtime)
    if choice is None or not _ensure_model_installed(choice):
        return 0
    return _run_command(["--model", choice.catalog_id or choice.ollama_tag, *base_args], runner)


def _projects_menu(runtime: Ci2LabConfig) -> int:
    from ci2lab.ui.projects import create_project, list_projects

    while True:
        projects = list_projects()
        options = [
            MenuOption(
                "Create new project",
                "Create an isolated workspace with its own sources and chats.",
                "create",
            ),
            *[
                MenuOption(
                    project["name"],
                    (
                        f"{project['source_count']} source"
                        f"{'' if project['source_count'] == 1 else 's'} · "
                        f"{project['source_size_label']}"
                    ),
                    project["id"],
                )
                for project in projects
            ],
            MenuOption("Back", "Return to the main menu.", "back"),
        ]
        selected = select_from_menu(
            "My projects",
            options,
            subtitle="Each project has independent sources and conversations.",
        )
        if selected in {None, "back"}:
            return 0
        if selected == "create":
            name = _ask_text("Project name")
            if not name:
                continue
            result = create_project(name)
            if not result.get("ok"):
                console.print(f"[red]{result.get('error', 'Could not create project.')}[/red]")
                continue
            project = result["project"]
            console.print(f"[green]Project created:[/green] {project['name']}")
            _project_detail_menu(runtime, project["id"])
            continue
        _project_detail_menu(runtime, selected)


def _project_detail_menu(runtime: Ci2LabConfig, project_id: str) -> int:
    from ci2lab.ui.projects import delete_project, get_project

    while True:
        project = get_project(project_id)
        if project is None:
            console.print("[yellow]Project not found.[/yellow]")
            return 0
        conversations = _project_sessions(project_id)
        options = (
            MenuOption(
                "Start new chat",
                "Classic chat using this project's sources on every turn.",
                "chat",
            ),
            MenuOption(
                "Start new multi-agent chat",
                "Use sequential agents with this project's sources.",
                "multi_chat",
            ),
            MenuOption(
                "Continue a conversation",
                f"{len(conversations)} saved project conversation(s).",
                "sessions",
            ),
            MenuOption(
                "Add source",
                "Upload a local document, PDF, notes, slides or spreadsheet.",
                "add_source",
            ),
            MenuOption(
                "View or remove sources",
                f"{project['source_count']} source(s) in this project.",
                "sources",
            ),
            MenuOption("Delete project", "Delete its sources and conversations.", "delete"),
            MenuOption("Back", "Return to My projects.", "back"),
        )
        selected = select_from_menu(
            project["name"],
            options,
            subtitle=(
                f"{project['source_count']} sources · "
                f"{len(conversations)} conversations"
            ),
        )
        if selected in {None, "back"}:
            return 0
        if selected == "chat":
            _run_project_chat(runtime, project_id, multi_agent=False)
        elif selected == "multi_chat":
            _run_project_chat(runtime, project_id, multi_agent=True)
        elif selected == "sessions":
            session = _select_project_session(project_id)
            if session:
                _run_project_chat(
                    runtime,
                    project_id,
                    session_id=session["id"],
                    multi_agent=False,
                )
        elif selected == "add_source":
            _add_project_source_from_path(project_id)
        elif selected == "sources":
            _project_sources_menu(project_id)
        elif selected == "delete":
            if _confirm(
                f"Delete project '{project['name']}' and all its sources/chats? [y/N] "
            ):
                result = delete_project(project_id)
                if result.get("ok"):
                    console.print("[green]Project deleted.[/green]")
                    return 0
                console.print(f"[red]{result.get('error', 'Could not delete project.')}[/red]")


def _run_project_chat(
    runtime: Ci2LabConfig,
    project_id: str,
    *,
    session_id: str | None = None,
    multi_agent: bool = False,
) -> int:
    from ci2lab.harness.repl import run_repl
    from ci2lab.pipeline import build_agent_config, prepare_session
    from ci2lab.ui.projects import get_project

    project = get_project(project_id)
    if project is None:
        console.print("[red]Project not found.[/red]")
        return 1
    choice = select_model(runtime)
    if choice is None or not _ensure_model_installed(choice):
        return 0
    _, selection = prepare_session(
        "",
        force_model=choice.ollama_tag,
        backend_url=runtime.backend_url,
        pull=False,
    )
    config = build_agent_config(
        runtime,
        selection,
        cwd=project["workspace"],
        session_id=session_id,
    )
    config.project_id = project_id
    console.print(
        f"[bold]Project:[/bold] {project['name']} "
        f"[dim]({project['source_count']} sources)[/dim]"
    )
    run_repl(
        selection,
        config,
        session_id=session_id,
        multi_agent=multi_agent,
    )
    return 0


def _project_sessions(project_id: str) -> list[dict[str, str]]:
    from ci2lab.harness.session import list_sessions

    return [
        row for row in list_sessions()
        if str(row.get("project_id") or "") == project_id
    ]


def _select_project_session(project_id: str) -> dict[str, str] | None:
    rows = _project_sessions(project_id)
    if not rows:
        console.print("[yellow]This project has no saved conversations yet.[/yellow]")
        return None
    options = []
    for row in rows:
        options.append(
            MenuOption(
                row.get("title") or "Conversation",
                f"{row['id']} · {row['updated_at'][:19]} · {row['model']}",
                row["id"],
            )
        )
    selected = select_from_menu("Project conversations", options)
    return next((row for row in rows if row["id"] == selected), None)


def _add_project_source_from_path(project_id: str) -> bool:
    from ci2lab.ui.projects import add_project_source

    raw_path = _ask_text("Path to source file")
    if not raw_path:
        return False
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        console.print(f"[red]File not found:[/red] {path}")
        return False
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        console.print(f"[red]Could not read file:[/red] {exc}")
        return False
    result = add_project_source(
        project_id,
        {"name": path.name, "content_base64": encoded},
    )
    if not result.get("ok"):
        console.print(f"[red]{result.get('error', 'Could not add source.')}[/red]")
        return False
    console.print(
        f"[green]Source added:[/green] {result['source']['name']} "
        f"({result['source']['size_label']})"
    )
    return True


def _project_sources_menu(project_id: str) -> int:
    from ci2lab.ui.projects import delete_project_source, list_project_sources

    while True:
        result = list_project_sources(project_id)
        sources = result.get("sources", []) if result.get("ok") else []
        options = [
            MenuOption("Add source", "Upload another local file.", "add"),
            *[
                MenuOption(
                    source["name"],
                    f"{source['size_label']} · select to remove",
                    source["id"],
                )
                for source in sources
            ],
            MenuOption("Back", "Return to the project.", "back"),
        ]
        selected = select_from_menu("Project sources", options)
        if selected in {None, "back"}:
            return 0
        if selected == "add":
            _add_project_source_from_path(project_id)
            continue
        source = next((item for item in sources if item["id"] == selected), None)
        if source and _confirm(f"Remove source '{source['name']}'? [y/N] "):
            removed = delete_project_source(project_id, source["id"])
            if removed.get("ok"):
                console.print("[green]Source removed.[/green]")
            else:
                console.print(f"[red]{removed.get('error', 'Could not remove source.')}[/red]")


def _sessions_menu(runner: CommandRunner) -> int:
    selected = select_from_menu("Sessions", SESSION_OPTIONS)
    if selected in {None, "back"}:
        return 0
    if selected == "list":
        return _run_command(["sessions"], runner)

    session = select_session()
    if session is None:
        return 0
    session_id = session["id"]
    if selected == "open_json":
        return open_session_json(session_id)
    if selected == "resume_chat":
        return _run_command(["--session", session_id, "chat"], runner)
    if selected == "resume_multi_chat":
        return _run_command(["--session", session_id, "--multi-agent", "chat"], runner)
    return 0


def _permissions_menu(runner: CommandRunner) -> int:
    selected = select_from_menu("Permissions dashboard", PERMISSIONS_OPTIONS)
    if selected in {None, "back"}:
        return 0
    args = ["permissions", selected]
    if selected in {"retry-plan", "approve-session"}:
        event_id = _ask_text("event_id")
        if not event_id:
            return 0
        args.append(event_id)
    return _run_command(args, runner)


def _evals_menu(runtime: Ci2LabConfig, runner: CommandRunner) -> int:
    selected = select_from_menu("Evals", EVAL_OPTIONS)
    if selected in {None, "back"}:
        return 0
    if selected == "mock":
        return _run_command(["evals", "run"], runner)
    choice = select_model(runtime)
    if choice is None or not _ensure_model_installed(choice):
        return 0
    return _run_command(
        ["evals", "run", "--live", "--model", choice.catalog_id or choice.ollama_tag],
        runner,
    )


def select_model(runtime: Ci2LabConfig | None = None) -> ModelChoice | None:
    choices, error = build_model_choices(runtime)
    subtitle = "Use Up/Down and Enter"
    if error:
        subtitle = f"Ollama status unavailable: {error}"
    selected = select_from_menu("Select model", choices, subtitle=subtitle)
    if selected is None:
        return None
    return next((choice for choice in choices if choice.value == selected), None)


def build_model_choices(
    runtime: Ci2LabConfig | None = None,
) -> tuple[list[ModelChoice], str | None]:
    backend_url = runtime.backend_url if runtime else None
    if backend_url:
        installed, error = fetch_installed_models(backend_url)
    else:
        installed, error = fetch_installed_models()
    installed_names = {str(item.get("name") or "") for item in installed}
    profile = scan_hardware()
    choices: list[ModelChoice] = []
    catalog_tags: set[str] = set()

    for model in load_model_catalog():
        installed_here = is_catalog_model_installed(model.ollama_tag, installed_names)
        fits_here = model_fits(model, profile)
        catalog_tags.add(model.ollama_tag.lower())
        status = "installed" if installed_here else "not installed"
        fit = "fits" if fits_here else "too large"
        choices.append(
            ModelChoice(
                label=(
                    f"{model.display_name} | {model.ollama_tag} "
                    f"({status}, {fit})"
                ),
                value=model.id,
                catalog_id=model.id,
                ollama_tag=model.ollama_tag,
                installed=installed_here,
                fits=fits_here,
            )
        )

    for item in installed:
        name = str(item.get("name") or "").strip()
        if not name or name.lower() in catalog_tags:
            continue
        choices.append(
            ModelChoice(
                label=f"{name} (installed, external)",
                value=name,
                catalog_id=None,
                ollama_tag=name,
                installed=True,
                fits=None,
            )
        )
    choices.sort(key=lambda choice: (not choice.installed, choice.label.lower()))
    return choices, error


def select_session() -> dict[str, str] | None:
    from ci2lab.harness.session import list_sessions

    rows = list_sessions()
    if not rows:
        console.print("[yellow]No saved sessions found.[/yellow]")
        return None
    options = [
        MenuOption(
            label=row.get("title") or "Conversation",
            description=(
                f"{row['id']} · {row['model']} · "
                f"{row['updated_at'][:19]}"
            ),
            value=row["id"],
        )
        for row in rows
    ]
    selected = select_from_menu("Select session", options)
    if selected is None:
        return None
    return next((row for row in rows if row["id"] == selected), None)


def open_session_json(session_id: str) -> int:
    from ci2lab.harness.session import sessions_dir

    path = sessions_dir() / f"{session_id}.json"
    if not path.is_file():
        console.print(f"[red]Session JSON not found:[/red] {path}")
        return 1
    console.print(f"[bold]Opening session JSON:[/bold] {path}")
    try:
        _open_path(path)
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not open the file automatically: {exc}[/yellow]")
        try:
            console.print_json(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            console.print(path.read_text(encoding="utf-8", errors="replace"))
        return 1


def select_from_menu(
    title: str,
    options: tuple[MenuOption, ...] | list[MenuOption] | list[ModelChoice],
    *,
    subtitle: str | None = None,
) -> str | None:
    """Arrow-key selector. Returns the selected option value or None on Escape."""
    if not options:
        console.print("[yellow]No options available.[/yellow]")
        return None
    if sys.stdin.isatty():
        try:
            return _select_from_menu_app(title, options, subtitle=subtitle)
        except ImportError:
            return _select_from_menu_raw(title, options, subtitle=subtitle)
    return _select_from_menu_numbered(title, options, subtitle=subtitle)


def _select_from_menu_app(
    title: str,
    options: tuple[MenuOption, ...] | list[MenuOption] | list[ModelChoice],
    *,
    subtitle: str | None,
) -> str | None:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    state: dict[str, int | str | None] = {"index": 0, "value": None}
    label_width = _menu_label_width(options)

    def fragments() -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        items.extend(_art_fragments())
        items.append(("", "\n"))
        items.append(("class:title", f"{title}\n"))
        if subtitle:
            items.append(("class:muted", f"{subtitle}\n"))
        items.append(("class:muted", "Use Up/Down, Enter to select, Esc or q to go back.\n\n"))

        selected_index = int(state["index"] or 0)
        start, end = _visible_option_window(
            total=len(options),
            selected_index=selected_index,
            subtitle=subtitle,
        )
        if start > 0:
            items.append(("class:muted", f"... {start} more above\n"))
        for pos, option in enumerate(options[start:end], start=start):
            is_selected = pos == selected_index
            pointer = "> " if is_selected else "  "
            label_style = "class:selected" if is_selected else ""
            if isinstance(option, MenuOption) and option.description:
                items.append((label_style, f"{pointer}{option.label:<{label_width - 2}} "))
                items.append(("class:muted", f"{option.description}\n"))
            else:
                items.append((label_style, f"{pointer}{option.label}\n"))
        if end < len(options):
            items.append(("class:muted", f"... {len(options) - end} more below\n"))
        return items

    control = FormattedTextControl(fragments, focusable=True)
    bindings = KeyBindings()

    def move(delta: int) -> None:
        state["index"] = (int(state["index"] or 0) + delta) % len(options)
        app.invalidate()

    @bindings.add("up")
    @bindings.add("k")
    @bindings.add("w")
    def _up(_event) -> None:  # noqa: ANN001
        move(-1)

    @bindings.add("down")
    @bindings.add("j")
    @bindings.add("s")
    def _down(_event) -> None:  # noqa: ANN001
        move(1)

    @bindings.add("enter")
    def _enter(_event) -> None:  # noqa: ANN001
        state["value"] = options[int(state["index"] or 0)].value
        app.exit()

    @bindings.add("escape")
    @bindings.add("q")
    @bindings.add("c-c")
    def _cancel(_event) -> None:  # noqa: ANN001
        state["value"] = None
        app.exit()

    style = Style.from_dict({
        "art.gear": "bold ansiblue",
        "art.name": "bold ansiyellow",
        "title": "bold",
        "muted": "ansibrightblack",
        "selected": "bold ansiyellow",
    })
    app = Application(
        layout=Layout(Window(content=control, always_hide_cursor=True)),
        key_bindings=bindings,
        full_screen=True,
        mouse_support=False,
        style=style,
    )
    app.run()
    value = state["value"]
    return str(value) if value is not None else None


def _select_from_menu_numbered(
    title: str,
    options: tuple[MenuOption, ...] | list[MenuOption] | list[ModelChoice],
    *,
    subtitle: str | None,
) -> str | None:
    """One-shot fallback for terminals without prompt_toolkit."""
    console.clear()
    _print_art()
    console.print(f"[bold]{title}[/bold]")
    if subtitle:
        console.print(f"[dim]{subtitle}[/dim]")
    console.print(
        "[yellow]Arrow selector unavailable because prompt_toolkit is not installed.[/yellow]"
    )
    console.print("[dim]Choose by number, or press Enter to go back.[/dim]\n")
    label_width = _menu_label_width(options)
    for pos, option in enumerate(options, start=1):
        label = f"{pos:>2}. {option.label}"
        if isinstance(option, MenuOption) and option.description:
            console.print(f"{label:<{label_width + 4}} [dim]{option.description}[/dim]")
        else:
            console.print(label)
    answer = _prompt_text("Choose a number, or press Enter to go back: ").strip()
    if not answer:
        return None
    try:
        index = int(answer) - 1
    except ValueError:
        return None
    if 0 <= index < len(options):
        return options[index].value
    return None


def _select_from_menu_raw(
    title: str,
    options: tuple[MenuOption, ...] | list[MenuOption] | list[ModelChoice],
    *,
    subtitle: str | None,
) -> str | None:
    """Minimal arrow-key selector using an alternate screen, no scroll spam."""
    index = 0
    _enter_alternate_screen()
    try:
        while True:
            _render_raw_menu(title, options, index, subtitle=subtitle)
            key = _read_key()
            if key == "up":
                index = (index - 1) % len(options)
            elif key == "down":
                index = (index + 1) % len(options)
            elif key == "enter":
                return options[index].value
            elif key in {"escape", "q"}:
                return None
    finally:
        _exit_alternate_screen()


def _render_raw_menu(
    title: str,
    options: tuple[MenuOption, ...] | list[MenuOption] | list[ModelChoice],
    index: int,
    *,
    subtitle: str | None,
) -> None:
    label_width = _menu_label_width(options)
    lines = [
        "\x1b[H\x1b[2J",
        _ansi_art(),
        "",
        title,
    ]
    if subtitle:
        lines.append(subtitle)
    lines.extend([
        "Use Up/Down, Enter to select, Esc or q to go back.",
        "",
    ])
    start, end = _visible_option_window(
        total=len(options),
        selected_index=index,
        subtitle=subtitle,
    )
    if start > 0:
        lines.append(f"{_ANSI_DIM}... {start} more above{_ANSI_RESET}")
    for pos, option in enumerate(options[start:end], start=start):
        pointer = "> " if pos == index else "  "
        selected = pos == index
        label_color = _ANSI_GOLD if selected else ""
        reset = _ANSI_RESET if selected else ""
        if isinstance(option, MenuOption) and option.description:
            lines.append(
                f"{label_color}{pointer}{option.label:<{label_width - 2}}{reset} "
                f"{_ANSI_DIM}{option.description}{_ANSI_RESET}"
            )
        else:
            lines.append(f"{label_color}{pointer}{option.label}{reset}")
    if end < len(options):
        lines.append(f"{_ANSI_DIM}... {len(options) - end} more below{_ANSI_RESET}")
    sys.stdout.write("\n".join(lines))
    sys.stdout.flush()


def _enter_alternate_screen() -> None:
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    sys.stdout.flush()


def _exit_alternate_screen() -> None:
    sys.stdout.write("\x1b[?25h\x1b[?1049l")
    sys.stdout.flush()


def _render_menu(
    title: str,
    options: tuple[MenuOption, ...] | list[MenuOption] | list[ModelChoice],
    index: int,
    *,
    subtitle: str | None,
) -> None:
    console.clear()
    _print_art()
    console.print(f"[bold]{title}[/bold]")
    if subtitle:
        console.print(f"[dim]{subtitle}[/dim]")
    console.print("[dim]Use Up/Down, Enter to select, Esc or q to go back.[/dim]\n")
    label_width = _menu_label_width(options)
    for pos, option in enumerate(options):
        pointer = ">" if pos == index else " "
        style = "bold yellow" if pos == index else ""
        label = f"{pointer} {option.label}"
        if isinstance(option, MenuOption) and option.description:
            console.print(
                f"{label:<{label_width}} [dim]{option.description}[/dim]",
                style=style,
            )
        else:
            console.print(label, style=style)


def _menu_label_width(
    options: tuple[MenuOption, ...] | list[MenuOption] | list[ModelChoice],
) -> int:
    labels = [option.label for option in options]
    return min(max((len(label) for label in labels), default=0) + 4, 42)


def _visible_option_window(
    *,
    total: int,
    selected_index: int,
    subtitle: str | None,
) -> tuple[int, int]:
    terminal_height = shutil.get_terminal_size((100, 30)).lines
    fixed_lines = len(WELCOME_ART.splitlines()) + 6
    if subtitle:
        fixed_lines += 1
    visible = max(3, terminal_height - fixed_lines)
    visible = min(total, visible)
    start = min(
        max(0, selected_index - visible + 1),
        max(0, total - visible),
    )
    return start, start + visible


def _art_fragments() -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    for line in WELCOME_ART.splitlines():
        style = "class:art.name" if "C I 2 L A B" in line else "class:art.gear"
        fragments.append((style, f"{line}\n"))
    return fragments


def _print_art() -> None:
    for line in WELCOME_ART.splitlines():
        style = "bold yellow" if "C I 2 L A B" in line else "bold blue"
        console.print(line, style=style)


def _ansi_art() -> str:
    lines = []
    for line in WELCOME_ART.splitlines():
        color = _ANSI_GOLD if "C I 2 L A B" in line else _ANSI_BLUE
        lines.append(f"{color}{line}{_ANSI_RESET}")
    return "\n".join(lines)


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            key = msvcrt.getwch()
            return {"H": "up", "P": "down"}.get(key, "")
        return _normalize_key(key)
    return _read_posix_key()


def _read_posix_key() -> str:
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        first = sys.stdin.read(1)
        if first == "\x1b":
            if not select.select([sys.stdin], [], [], 0.05)[0]:
                return "escape"
            rest = sys.stdin.read(2)
            if rest == "[A":
                return "up"
            if rest == "[B":
                return "down"
            return "escape"
        return _normalize_key(first)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _normalize_key(key: str) -> str:
    if key in ("\r", "\n"):
        return "enter"
    if key == "\x1b":
        return "escape"
    if key.lower() == "q":
        return "q"
    if key.lower() in {"k", "w"}:
        return "up"
    if key.lower() in {"j", "s"}:
        return "down"
    return ""


def _ensure_model_installed(choice: ModelChoice) -> bool:
    if choice.installed:
        return True
    console.print(f"[yellow]Model not installed:[/yellow] {choice.ollama_tag}")
    if choice.fits is False:
        console.print(
            "[yellow]This model may be too large for the current inference budget.[/yellow]"
        )
    answer = _prompt_text("Download it now with `ollama pull`? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        return False
    return _pull_model(choice.ollama_tag) == 0


def _pull_model(ollama_tag: str) -> int:
    console.print(f"[bold]$[/bold] ollama pull {ollama_tag}")
    try:
        completed = subprocess.run(["ollama", "pull", ollama_tag], check=False)
    except FileNotFoundError:
        console.print("[red]Could not find the `ollama` command.[/red]")
        return 1
    finally:
        _print_divider()
    return completed.returncode


def _run_direct_ollama(ollama_tag: str) -> int:
    console.print(f"[bold]$[/bold] ollama run {ollama_tag}")
    try:
        completed = subprocess.run(["ollama", "run", ollama_tag], check=False)
    except FileNotFoundError:
        console.print("[red]Could not find the `ollama` command.[/red]")
        return 1
    finally:
        _print_divider()
    return completed.returncode


def _run_command(args: list[str], runner: CommandRunner) -> int:
    console.print(f"\n[bold]$[/bold] ci2lab {_format_args(args)}\n")
    try:
        return runner(args)
    finally:
        _print_divider()


def _run_doctor_with_ollama_install_option(runner: CommandRunner) -> int:
    code = _run_command(["doctor"], runner)
    if _ollama_executable_found():
        return code

    console.print("[yellow]Ollama does not appear to be installed.[/yellow]")
    action = _ollama_install_action()
    if action is None:
        console.print(
            "[yellow]Automatic installation is not configured for this platform.[/yellow]"
        )
        if _confirm("Open the Ollama download page? [y/N] "):
            return _open_ollama_download_page()
        return code

    label, command = action
    console.print(f"[bold]Installer:[/bold] {label}")
    console.print(f"[bold]$[/bold] {_format_args(command)}")
    if not _confirm("Install Ollama now? [y/N] "):
        return code
    try:
        completed = subprocess.run(command, check=False)
        return completed.returncode
    except FileNotFoundError:
        console.print(f"[red]Installer command not found:[/red] {command[0]}")
        return 1
    finally:
        _print_divider()


def _ollama_executable_found() -> bool:
    return bool(ollama_install_info().get("executable"))


def _ollama_install_action() -> tuple[str, list[str]] | None:
    if os.name == "nt" and shutil.which("winget"):
        return (
            "Windows Package Manager",
            ["winget", "install", "--id", "Ollama.Ollama", "-e"],
        )
    if sys.platform == "darwin" and shutil.which("brew"):
        return ("Homebrew", ["brew", "install", "--cask", "ollama"])
    return None


def _open_ollama_download_page() -> int:
    try:
        webbrowser.open("https://ollama.com/download")
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not open the browser: {exc}[/yellow]")
        console.print("Download Ollama from: https://ollama.com/download")
        return 1
    finally:
        _print_divider()


def _confirm(message: str) -> bool:
    return _prompt_text(message).strip().lower() in {"y", "yes"}


def _print_divider() -> None:
    console.rule(style="dim")


def _command_mode(runner: CommandRunner) -> int:
    console.clear()
    _print_art()
    console.print("[bold]Work with commands[/bold]")
    console.print(
        "[dim]Type the arguments exactly as you would after `ci2lab`. "
        "Examples: `chat`, `doctor`, `models recommend`, "
        '`agent "list Python files"`. Leave empty to go back.[/dim]\n'
    )
    line = _ask_text("ci2lab").strip()
    if not line:
        return 0
    args = _parse_command_line(line)
    if args and args[0].lower() == "ci2lab":
        args = args[1:]
    if not args:
        return 0
    return _run_command(args, runner)


def _parse_command_line(line: str) -> list[str]:
    try:
        parts = shlex.split(line, posix=False)
    except ValueError as exc:
        console.print(f"[red]Could not parse command:[/red] {exc}")
        return []
    return [_strip_outer_quotes(part) for part in parts]


def _strip_outer_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _format_args(args: list[str]) -> str:
    return " ".join(_quote_arg(arg) for arg in args)


def _quote_arg(arg: str) -> str:
    if not arg or any(char.isspace() for char in arg):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg


def _ask_text(label: str) -> str:
    return _prompt_text(f"{label}: ").strip()


def _pause() -> None:
    try:
        _prompt_text("\nPress Enter to return to the menu...")
    except (EOFError, KeyboardInterrupt):
        return


def _prompt_text(message: str) -> str:
    try:
        from prompt_toolkit import prompt
    except ImportError:
        return input(message)
    return prompt(message)


def _default_command_runner(args: list[str]) -> int:
    from ci2lab.cli.main import main

    return main(args)


def _open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.run([opener, str(path)], check=True)


def _print_about() -> None:
    console.print("[bold]What is ci2lab?[/bold]\n")
    console.print(
        "ci2lab is a local CLI and web UI for running Ollama models as an "
        "agent with tools. It can inspect your hardware, recommend models, "
        "chat with files and code, use supervised edit tools, keep sessions, "
        "load workspace skills, connect MCP tools, and run security-aware "
        "permission checks."
    )
    console.print(
        "\nClassic chat uses one ReAct agent. Multi-agent chat runs a sequential "
        "planner, researcher, coder, validator, and reviewer over the same "
        "agent engine."
    )
