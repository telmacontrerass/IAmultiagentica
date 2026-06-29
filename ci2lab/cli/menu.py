"""Interactive startup menu for the ci2lab CLI."""

from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    """A selectable menu entry with a label, description and return value."""

    label: str
    description: str
    value: str


@dataclass(frozen=True)
class ModelChoice:
    """A selectable model entry, carrying its Ollama tag and install/fit status."""

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
INTERNAL_LANGUAGE = "en"
SUPPORTED_DISPLAY_LANGUAGES = ("en", "es", "fr", "pt")
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "pt": "Português",
}
_CURRENT_DISPLAY_LANGUAGE = INTERNAL_LANGUAGE

CLI_TRANSLATIONS: dict[str, dict[str, str]] = {
    "es": {
        "Open web interface": "Abrir interfaz web",
        "Start the local browser UI.": "Inicia la UI local en el navegador.",
        "Start chat with tools": "Iniciar chat con herramientas",
        "Classic ci2lab chat with the selected model.": "Chat clásico de ci2lab con el modelo seleccionado.",
        "My projects": "Mis proyectos",
        "Open a project, manage its sources and continue its chats.": "Abre un proyecto, gestiona sus fuentes y continúa sus chats.",
        "Start chat with agents": "Iniciar chat con agentes",
        "Sequential planner/researcher/coder/validator/reviewer flow.": "Flujo secuencial de planificador/investigador/programador/validador/revisor.",
        "Start simple tools chat": "Iniciar chat simple con herramientas",
        "Fenced tool mode and no streaming, matching `ci2lab tools`.": "Modo de herramientas delimitado y sin streaming, como `ci2lab tools`.",
        "Run one-shot agent task": "Ejecutar tarea única del agente",
        "Write a prompt and run one agent turn.": "Escribe un prompt y ejecuta un turno del agente.",
        "Check Ollama and environment": "Comprobar Ollama y entorno",
        "Run `ci2lab doctor`.": "Ejecuta `ci2lab doctor`.",
        "Check computer hardware": "Comprobar hardware del equipo",
        "Show RAM/GPU/inference budget.": "Muestra RAM/GPU/capacidad de inferencia.",
        "Recommend models for this computer": "Recomendar modelos para este equipo",
        "General download plan based on local hardware.": "Plan general de descarga basado en el hardware local.",
        "Recommend models for a task": "Recomendar modelos para una tarea",
        "Describe the task and rank catalog models for it.": "Describe la tarea y ordena los modelos del catálogo.",
        "Install/download a model": "Instalar/descargar un modelo",
        "Pick a model and run `ollama pull`.": "Elige un modelo y ejecuta `ollama pull`.",
        "Open direct Ollama chat": "Abrir chat directo de Ollama",
        "Pick a model and run `ollama run`.": "Elige un modelo y ejecuta `ollama run`.",
        "Sessions": "Sesiones",
        "Open session JSON files or resume a saved chat.": "Abre archivos JSON de sesión o reanuda un chat guardado.",
        "Permissions dashboard": "Panel de permisos",
        "Audit permissions and session approvals.": "Audita permisos y aprobaciones de sesión.",
        "Run evals": "Ejecutar evaluaciones",
        "Run mock or live harness evaluations.": "Ejecuta evaluaciones simuladas o reales.",
        "What is ci2lab?": "¿Qué es ci2lab?",
        "Short explanation of this program.": "Explicación breve de este programa.",
        "Show command help": "Mostrar ayuda de comandos",
        "Print the classic command reference.": "Imprime la referencia clásica de comandos.",
        "Work with commands": "Trabajar con comandos",
        "Type and run ci2lab commands manually.": "Escribe y ejecuta comandos de ci2lab manualmente.",
        "Change language": "Cambiar idioma",
        "Choose the language used by this terminal menu only.": "Elige el idioma usado solo por este menú de terminal.",
        "Exit": "Salir",
        "Close this launcher.": "Cierra este lanzador.",
        "ci2lab launcher": "Lanzador de ci2lab",
        "Workspace:": "Workspace:",
        "Bye.": "Adiós.",
        "Language": "Idioma",
        "Current language:": "Idioma actual:",
        "Terminal language updated:": "Idioma de terminal actualizado:",
        "Display language only. Internal prompts, tools and model messages remain in English.": "Solo idioma visual. Los prompts internos, herramientas y mensajes del modelo siguen en inglés.",
        "Back": "Volver",
        "Return to the main menu.": "Volver al menú principal.",
        "Use Up/Down and Enter": "Usa Arriba/Abajo y Enter",
        "Use Up/Down, Enter to select, Esc or q to go back.": "Usa Arriba/Abajo, Enter para seleccionar, Esc o q para volver.",
        "Choose by number, or press Enter to go back.": "Elige por número o pulsa Enter para volver.",
        "Choose a number, or press Enter to go back: ": "Elige un número o pulsa Enter para volver: ",
        "Arrow selector unavailable because prompt_toolkit is not installed.": "El selector con flechas no está disponible porque prompt_toolkit no está instalado.",
        "No options available.": "No hay opciones disponibles.",
        "Press Enter to return to the menu...": "Pulsa Enter para volver al menú...",
        "Select model": "Seleccionar modelo",
        "Select session": "Seleccionar sesión",
        "installed": "instalado",
        "not installed": "no instalado",
        "fits": "encaja",
        "too large": "demasiado grande",
        "external": "externo",
    },
    "fr": {
        "Open web interface": "Ouvrir l'interface web",
        "Start the local browser UI.": "Démarre l'interface locale dans le navigateur.",
        "Start chat with tools": "Démarrer un chat avec outils",
        "Classic ci2lab chat with the selected model.": "Chat ci2lab classique avec le modèle sélectionné.",
        "My projects": "Mes projets",
        "Open a project, manage its sources and continue its chats.": "Ouvrir un projet, gérer ses sources et continuer ses chats.",
        "Start chat with agents": "Démarrer un chat avec agents",
        "Sequential planner/researcher/coder/validator/reviewer flow.": "Flux séquentiel planificateur/chercheur/codeur/validateur/relecteur.",
        "Start simple tools chat": "Démarrer un chat simple avec outils",
        "Fenced tool mode and no streaming, matching `ci2lab tools`.": "Mode outils délimité sans streaming, comme `ci2lab tools`.",
        "Run one-shot agent task": "Exécuter une tâche agent unique",
        "Write a prompt and run one agent turn.": "Écrire un prompt et exécuter un tour d'agent.",
        "Check Ollama and environment": "Vérifier Ollama et l'environnement",
        "Run `ci2lab doctor`.": "Exécute `ci2lab doctor`.",
        "Check computer hardware": "Vérifier le matériel",
        "Show RAM/GPU/inference budget.": "Afficher RAM/GPU/budget d'inférence.",
        "Recommend models for this computer": "Recommander des modèles pour cet ordinateur",
        "General download plan based on local hardware.": "Plan général de téléchargement selon le matériel local.",
        "Recommend models for a task": "Recommander des modèles pour une tâche",
        "Describe the task and rank catalog models for it.": "Décrire la tâche et classer les modèles du catalogue.",
        "Install/download a model": "Installer/télécharger un modèle",
        "Pick a model and run `ollama pull`.": "Choisir un modèle et exécuter `ollama pull`.",
        "Open direct Ollama chat": "Ouvrir un chat Ollama direct",
        "Pick a model and run `ollama run`.": "Choisir un modèle et exécuter `ollama run`.",
        "Sessions": "Sessions",
        "Open session JSON files or resume a saved chat.": "Ouvrir des fichiers JSON de session ou reprendre un chat enregistré.",
        "Permissions dashboard": "Tableau des permissions",
        "Audit permissions and session approvals.": "Auditer les permissions et approbations de session.",
        "Run evals": "Exécuter les évaluations",
        "Run mock or live harness evaluations.": "Exécuter des évaluations simulées ou réelles.",
        "What is ci2lab?": "Qu'est-ce que ci2lab ?",
        "Short explanation of this program.": "Brève explication de ce programme.",
        "Show command help": "Afficher l'aide des commandes",
        "Print the classic command reference.": "Afficher la référence classique des commandes.",
        "Work with commands": "Travailler avec des commandes",
        "Type and run ci2lab commands manually.": "Saisir et exécuter des commandes ci2lab manuellement.",
        "Change language": "Changer de langue",
        "Choose the language used by this terminal menu only.": "Choisir la langue utilisée uniquement par ce menu terminal.",
        "Exit": "Quitter",
        "Close this launcher.": "Fermer ce lanceur.",
        "ci2lab launcher": "Lanceur ci2lab",
        "Workspace:": "Workspace :",
        "Bye.": "Au revoir.",
        "Language": "Langue",
        "Current language:": "Langue actuelle :",
        "Terminal language updated:": "Langue du terminal mise à jour :",
        "Display language only. Internal prompts, tools and model messages remain in English.": "Langue d'affichage seulement. Les prompts internes, outils et messages du modèle restent en anglais.",
        "Back": "Retour",
        "Return to the main menu.": "Retour au menu principal.",
        "Use Up/Down and Enter": "Utilisez Haut/Bas et Entrée",
        "Use Up/Down, Enter to select, Esc or q to go back.": "Utilisez Haut/Bas, Entrée pour sélectionner, Esc ou q pour revenir.",
        "Choose by number, or press Enter to go back.": "Choisissez par numéro ou appuyez sur Entrée pour revenir.",
        "Choose a number, or press Enter to go back: ": "Choisissez un numéro ou appuyez sur Entrée pour revenir : ",
        "Arrow selector unavailable because prompt_toolkit is not installed.": "Le sélecteur par flèches est indisponible car prompt_toolkit n'est pas installé.",
        "No options available.": "Aucune option disponible.",
        "Press Enter to return to the menu...": "Appuyez sur Entrée pour revenir au menu...",
        "Select model": "Sélectionner un modèle",
        "Select session": "Sélectionner une session",
        "installed": "installé",
        "not installed": "non installé",
        "fits": "compatible",
        "too large": "trop grand",
        "external": "externe",
    },
    "pt": {
        "Open web interface": "Abrir interface web",
        "Start the local browser UI.": "Inicia a UI local no navegador.",
        "Start chat with tools": "Iniciar chat com ferramentas",
        "Classic ci2lab chat with the selected model.": "Chat clássico do ci2lab com o modelo selecionado.",
        "My projects": "Os meus projetos",
        "Open a project, manage its sources and continue its chats.": "Abrir um projeto, gerir as fontes e continuar os chats.",
        "Start chat with agents": "Iniciar chat com agentes",
        "Sequential planner/researcher/coder/validator/reviewer flow.": "Fluxo sequencial de planeador/investigador/programador/validador/revisor.",
        "Start simple tools chat": "Iniciar chat simples com ferramentas",
        "Fenced tool mode and no streaming, matching `ci2lab tools`.": "Modo de ferramentas delimitado e sem streaming, como `ci2lab tools`.",
        "Run one-shot agent task": "Executar tarefa única do agente",
        "Write a prompt and run one agent turn.": "Escrever um prompt e executar um turno do agente.",
        "Check Ollama and environment": "Verificar Ollama e ambiente",
        "Run `ci2lab doctor`.": "Executa `ci2lab doctor`.",
        "Check computer hardware": "Verificar hardware do computador",
        "Show RAM/GPU/inference budget.": "Mostrar RAM/GPU/capacidade de inferência.",
        "Recommend models for this computer": "Recomendar modelos para este computador",
        "General download plan based on local hardware.": "Plano geral de download baseado no hardware local.",
        "Recommend models for a task": "Recomendar modelos para uma tarefa",
        "Describe the task and rank catalog models for it.": "Descrever a tarefa e classificar modelos do catálogo.",
        "Install/download a model": "Instalar/descarregar um modelo",
        "Pick a model and run `ollama pull`.": "Escolher um modelo e executar `ollama pull`.",
        "Open direct Ollama chat": "Abrir chat direto do Ollama",
        "Pick a model and run `ollama run`.": "Escolher um modelo e executar `ollama run`.",
        "Sessions": "Sessões",
        "Open session JSON files or resume a saved chat.": "Abrir ficheiros JSON de sessão ou retomar um chat guardado.",
        "Permissions dashboard": "Painel de permissões",
        "Audit permissions and session approvals.": "Auditar permissões e aprovações de sessão.",
        "Run evals": "Executar avaliações",
        "Run mock or live harness evaluations.": "Executar avaliações simuladas ou reais.",
        "What is ci2lab?": "O que é o ci2lab?",
        "Short explanation of this program.": "Breve explicação deste programa.",
        "Show command help": "Mostrar ajuda de comandos",
        "Print the classic command reference.": "Imprimir a referência clássica de comandos.",
        "Work with commands": "Trabalhar com comandos",
        "Type and run ci2lab commands manually.": "Escrever e executar comandos ci2lab manualmente.",
        "Change language": "Alterar idioma",
        "Choose the language used by this terminal menu only.": "Escolher o idioma usado apenas por este menu do terminal.",
        "Exit": "Sair",
        "Close this launcher.": "Fechar este lançador.",
        "ci2lab launcher": "Lançador ci2lab",
        "Workspace:": "Workspace:",
        "Bye.": "Adeus.",
        "Language": "Idioma",
        "Current language:": "Idioma atual:",
        "Terminal language updated:": "Idioma do terminal atualizado:",
        "Display language only. Internal prompts, tools and model messages remain in English.": "Apenas idioma visual. Prompts internos, ferramentas e mensagens do modelo continuam em inglês.",
        "Back": "Voltar",
        "Return to the main menu.": "Voltar ao menu principal.",
        "Use Up/Down and Enter": "Use Cima/Baixo e Enter",
        "Use Up/Down, Enter to select, Esc or q to go back.": "Use Cima/Baixo, Enter para selecionar, Esc ou q para voltar.",
        "Choose by number, or press Enter to go back.": "Escolha por número ou prima Enter para voltar.",
        "Choose a number, or press Enter to go back: ": "Escolha um número ou prima Enter para voltar: ",
        "Arrow selector unavailable because prompt_toolkit is not installed.": "O seletor com setas não está disponível porque prompt_toolkit não está instalado.",
        "No options available.": "Não há opções disponíveis.",
        "Press Enter to return to the menu...": "Prima Enter para voltar ao menu...",
        "Select model": "Selecionar modelo",
        "Select session": "Selecionar sessão",
        "installed": "instalado",
        "not installed": "não instalado",
        "fits": "compatível",
        "too large": "demasiado grande",
        "external": "externo",
    },
}


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
    MenuOption(
        "Change language",
        "Choose the language used by this terminal menu only.",
        "language",
    ),
    MenuOption("Exit", "Close this launcher.", "exit"),
)


LANGUAGE_OPTIONS: tuple[MenuOption, ...] = (
    MenuOption(
        "English",
        "Display language only. Internal prompts, tools and model messages remain in English.",
        "en",
    ),
    MenuOption(
        "Español",
        "Display language only. Internal prompts, tools and model messages remain in English.",
        "es",
    ),
    MenuOption(
        "Français",
        "Display language only. Internal prompts, tools and model messages remain in English.",
        "fr",
    ),
    MenuOption(
        "Português",
        "Display language only. Internal prompts, tools and model messages remain in English.",
        "pt",
    ),
    MenuOption("Back", "Return to the main menu.", "back"),
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


def _language_config_path() -> Path:
    """Return the path of the persisted display-language preference file."""
    return Path(os.environ.get("CI2LAB_LANGUAGE_FILE", Path.home() / ".ci2lab" / "language.json"))


def _t(text: str) -> str:
    """Translate a UI string into the current display language (identity for English)."""
    if _CURRENT_DISPLAY_LANGUAGE == INTERNAL_LANGUAGE:
        return text
    return CLI_TRANSLATIONS.get(_CURRENT_DISPLAY_LANGUAGE, {}).get(text, text)


def _translated_menu_options(
    options: Sequence[MenuOption | ModelChoice],
) -> list[MenuOption | ModelChoice]:
    """Return a copy of the options with menu labels/descriptions translated.

    :class:`ModelChoice` entries are passed through unchanged since their labels
    are built from live data.
    """
    translated: list[MenuOption | ModelChoice] = []
    for option in options:
        if isinstance(option, MenuOption):
            translated.append(MenuOption(_t(option.label), _t(option.description), option.value))
        else:
            translated.append(option)
    return translated


def _translate_subtitle(subtitle: str | None) -> str | None:
    """Translate a menu subtitle, preserving the workspace path after the label."""
    if not subtitle:
        return None
    if subtitle.startswith("Workspace:"):
        return subtitle.replace("Workspace:", _t("Workspace:"), 1)
    return _t(subtitle)


def _load_display_language() -> str:
    """Load the display language from env or the config file, defaulting to English.

    Updates the module-level current language and returns the resolved value.
    """
    global _CURRENT_DISPLAY_LANGUAGE
    raw = os.environ.get("CI2LAB_DISPLAY_LANGUAGE", "")
    if not raw:
        try:
            data = json.loads(_language_config_path().read_text(encoding="utf-8"))
            raw = str(data.get("display_language") or "")
        except (OSError, json.JSONDecodeError):
            raw = ""
    _CURRENT_DISPLAY_LANGUAGE = raw if raw in SUPPORTED_DISPLAY_LANGUAGES else INTERNAL_LANGUAGE
    return _CURRENT_DISPLAY_LANGUAGE


def _save_display_language(language: str) -> None:
    """Persist a supported display language, updating the current value.

    Unsupported languages and filesystem errors are ignored silently.
    """
    if language not in SUPPORTED_DISPLAY_LANGUAGES:
        return
    global _CURRENT_DISPLAY_LANGUAGE
    _CURRENT_DISPLAY_LANGUAGE = language
    path = _language_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"display_language": language, "internal_language": INTERNAL_LANGUAGE}, indent=2
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def _language_menu() -> int:
    """Show the language picker and persist the chosen display language."""
    selected = select_from_menu(
        "Language",
        LANGUAGE_OPTIONS,
        subtitle=(
            f"{_t('Current language:')} {LANGUAGE_NAMES.get(_CURRENT_DISPLAY_LANGUAGE, 'English')} · "
            f"{_t('Display language only. Internal prompts, tools and model messages remain in English.')}"
        ),
    )
    if selected is None or selected == "back":
        return 0
    _save_display_language(selected)
    console.print(
        f"[green]{_t('Terminal language updated:')}[/green] "
        f"{LANGUAGE_NAMES.get(selected, selected)}"
    )
    return 0


def run_start_menu(
    runtime: Ci2LabConfig,
    *,
    command_runner: CommandRunner | None = None,
) -> int:
    """Show the interactive launcher until the user exits.

    Args:
        runtime: The merged runtime configuration (used for the workspace label
            and to drive chat/model commands).
        command_runner: Callable used to execute ``ci2lab`` subcommands; defaults
            to dispatching back into :func:`ci2lab.cli.main.main`. Injectable for
            tests.

    Returns:
        Process exit code; non-zero when a chat/ui command fails, ``0`` otherwise.
    """
    _load_display_language()
    runner = command_runner or _default_command_runner
    while True:
        selected = select_from_menu(
            "ci2lab launcher",
            MAIN_OPTIONS,
            subtitle=f"Workspace: {runtime.workspace or os.getcwd()}",
        )
        if selected is None or selected == "exit":
            console.print(f"[dim]{_t('Bye.')}[/dim]")
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
    """Dispatch a main-menu selection to the matching action.

    Args:
        selected: The ``value`` of the chosen :class:`MenuOption`.
        runtime: The merged runtime configuration.
        runner: Callable used to execute ``ci2lab`` subcommands.

    Returns:
        Process exit code from the dispatched action.
    """
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
    if selected == "language":
        return _language_menu()
    return 0


def _run_chat_command(
    runtime: Ci2LabConfig,
    runner: CommandRunner,
    base_args: list[str],
) -> int:
    """Pick and ensure a model, then run a chat command with ``--model`` prepended."""
    choice = select_model(runtime)
    if choice is None or not _ensure_model_installed(choice):
        return 0
    return _run_command(["--model", choice.catalog_id or choice.ollama_tag, *base_args], runner)


def _projects_menu(runtime: Ci2LabConfig) -> int:
    """Show the projects list, allowing creation and opening of a project."""
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
        if selected is None or selected == "back":
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
    """Show actions for a single project (chat, sources, delete) until Back."""
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
            subtitle=(f"{project['source_count']} sources · {len(conversations)} conversations"),
        )
        if selected is None or selected == "back":
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
            if _confirm(f"Delete project '{project['name']}' and all its sources/chats? [y/N] "):
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
    """Open a chat REPL scoped to a project's workspace and sources.

    Args:
        runtime: The merged runtime configuration.
        project_id: Identifier of the project to chat within.
        session_id: Optional saved session to resume.
        multi_agent: When True, use the multi-agent orchestrator.

    Returns:
        Process exit code: ``0`` on success, ``1`` if the project is missing.
    """
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
        backend=runtime.backend,
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
        f"[bold]Project:[/bold] {project['name']} [dim]({project['source_count']} sources)[/dim]"
    )
    run_repl(
        selection,
        config,
        session_id=session_id,
        multi_agent=multi_agent,
    )
    return 0


def _project_sessions(project_id: str) -> list[dict[str, str]]:
    """Return the saved session rows that belong to the given project."""
    from ci2lab.harness.session import list_sessions

    return [row for row in list_sessions() if str(row.get("project_id") or "") == project_id]


def _select_project_session(project_id: str) -> dict[str, str] | None:
    """Prompt the user to pick one of a project's saved conversations.

    Returns:
        The selected session row, or ``None`` if there are none or the user
        cancels.
    """
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
    """Prompt for a file path and add it as a base64-encoded project source.

    Returns:
        ``True`` if the source was added, ``False`` on cancel or any error.
    """
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
    """Show a project's sources, allowing adding and removing them until Back."""
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
        if selected is None or selected == "back":
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
    """Show the sessions submenu (open JSON, resume, list)."""
    selected = select_from_menu("Sessions", SESSION_OPTIONS)
    if selected is None or selected == "back":
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
    """Show the permissions submenu and run the chosen ``permissions`` subcommand."""
    selected = select_from_menu("Permissions dashboard", PERMISSIONS_OPTIONS)
    if selected is None or selected == "back":
        return 0
    args = ["permissions", selected]
    if selected in {"retry-plan", "approve-session"}:
        event_id = _ask_text("event_id")
        if not event_id:
            return 0
        args.append(event_id)
    return _run_command(args, runner)


def _evals_menu(runtime: Ci2LabConfig, runner: CommandRunner) -> int:
    """Show the evals submenu and run mock or live evaluations."""
    selected = select_from_menu("Evals", EVAL_OPTIONS)
    if selected is None or selected == "back":
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
    """Prompt the user to pick a model from the catalog and installed models.

    Args:
        runtime: Optional runtime configuration providing the backend URL.

    Returns:
        The selected :class:`ModelChoice`, or ``None`` if the user cancels.
    """
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
    """Build the model picker entries from the catalog and installed models.

    Catalog models are annotated with install and fit status; installed models
    not present in the catalog are appended as "external". The list is sorted so
    installed models come first.

    Args:
        runtime: Optional runtime configuration providing the backend URL.

    Returns:
        A tuple ``(choices, error)`` where ``error`` is the Ollama query error
        message (or ``None`` on success).
    """
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
        status = _t("installed" if installed_here else "not installed")
        fit = _t("fits" if fits_here else "too large")
        choices.append(
            ModelChoice(
                label=(f"{model.display_name} | {model.ollama_tag} ({status}, {fit})"),
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
                label=f"{name} ({_t('installed')}, {_t('external')})",
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
    """Prompt the user to pick one of the saved sessions.

    Returns:
        The selected session row, or ``None`` if there are none or the user
        cancels.
    """
    from ci2lab.harness.session import list_sessions

    rows = list_sessions()
    if not rows:
        console.print("[yellow]No saved sessions found.[/yellow]")
        return None
    options = [
        MenuOption(
            label=row.get("title") or "Conversation",
            description=(f"{row['id']} · {row['model']} · {row['updated_at'][:19]}"),
            value=row["id"],
        )
        for row in rows
    ]
    selected = select_from_menu("Select session", options)
    if selected is None:
        return None
    return next((row for row in rows if row["id"] == selected), None)


def open_session_json(session_id: str) -> int:
    """Open the saved session JSON file, falling back to printing its contents.

    Args:
        session_id: Identifier of the session whose JSON file to open.

    Returns:
        Process exit code: ``0`` if the file opened, ``1`` if it is missing or
        could not be opened automatically.
    """
    from ci2lab.harness.session import sessions_dir

    path = sessions_dir() / f"{session_id}.json"
    if not path.is_file():
        console.print(f"[red]Session JSON not found:[/red] {path}")
        return 1
    console.print(f"[bold]Opening session JSON:[/bold] {path}")
    try:
        _open_path(path)
        return 0
    except Exception as exc:
        console.print(f"[yellow]Could not open the file automatically: {exc}[/yellow]")
        try:
            console.print_json(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            console.print(path.read_text(encoding="utf-8", errors="replace"))
        return 1


def select_from_menu(
    title: str,
    options: Sequence[MenuOption | ModelChoice],
    *,
    subtitle: str | None = None,
) -> str | None:
    """Arrow-key selector. Returns the selected option value or None on Escape."""
    if not options:
        console.print(f"[yellow]{_t('No options available.')}[/yellow]")
        return None
    display_options = _translated_menu_options(options)
    display_title = _t(title)
    display_subtitle = _translate_subtitle(subtitle)
    if sys.stdin.isatty():
        try:
            return _select_from_menu_app(display_title, display_options, subtitle=display_subtitle)
        except ImportError:
            return _select_from_menu_raw(display_title, display_options, subtitle=display_subtitle)
    return _select_from_menu_numbered(display_title, display_options, subtitle=display_subtitle)


def _select_from_menu_app(
    title: str,
    options: Sequence[MenuOption | ModelChoice],
    *,
    subtitle: str | None,
) -> str | None:
    """Full-screen prompt_toolkit selector; returns the chosen value or None.

    Raises:
        ImportError: If prompt_toolkit is not installed (callers fall back to the
            raw selector).
    """
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
        items.append(
            ("class:muted", f"{_t('Use Up/Down, Enter to select, Esc or q to go back.')}\n\n")
        )

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
    def _up(_event: object) -> None:
        move(-1)

    @bindings.add("down")
    @bindings.add("j")
    @bindings.add("s")
    def _down(_event: object) -> None:
        move(1)

    @bindings.add("enter")
    def _enter(_event: object) -> None:
        state["value"] = options[int(state["index"] or 0)].value
        app.exit()

    @bindings.add("escape")
    @bindings.add("q")
    @bindings.add("c-c")
    def _cancel(_event: object) -> None:
        state["value"] = None
        app.exit()

    style = Style.from_dict(
        {
            "art.gear": "bold ansiblue",
            "art.name": "bold ansiyellow",
            "title": "bold",
            "muted": "ansibrightblack",
            "selected": "bold ansiyellow",
        }
    )
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
    options: Sequence[MenuOption | ModelChoice],
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
        f"[yellow]{_t('Arrow selector unavailable because prompt_toolkit is not installed.')}[/yellow]"
    )
    console.print(f"[dim]{_t('Choose by number, or press Enter to go back.')}[/dim]\n")
    label_width = _menu_label_width(options)
    for pos, option in enumerate(options, start=1):
        label = f"{pos:>2}. {option.label}"
        if isinstance(option, MenuOption) and option.description:
            console.print(f"{label:<{label_width + 4}} [dim]{option.description}[/dim]")
        else:
            console.print(label)
    answer = _prompt_text(_t("Choose a number, or press Enter to go back: ")).strip()
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
    options: Sequence[MenuOption | ModelChoice],
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
    options: Sequence[MenuOption | ModelChoice],
    index: int,
    *,
    subtitle: str | None,
) -> None:
    """Render one frame of the raw ANSI menu to stdout."""
    label_width = _menu_label_width(options)
    lines = [
        "\x1b[H\x1b[2J",
        _ansi_art(),
        "",
        title,
    ]
    if subtitle:
        lines.append(subtitle)
    lines.extend(
        [
            _t("Use Up/Down, Enter to select, Esc or q to go back."),
            "",
        ]
    )
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
    """Switch the terminal to the alternate screen buffer and hide the cursor."""
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    sys.stdout.flush()


def _exit_alternate_screen() -> None:
    """Restore the main screen buffer and show the cursor again."""
    sys.stdout.write("\x1b[?25h\x1b[?1049l")
    sys.stdout.flush()


def _render_menu(
    title: str,
    options: Sequence[MenuOption | ModelChoice],
    index: int,
    *,
    subtitle: str | None,
) -> None:
    """Render the menu via the Rich console (used by the Rich-based selector path)."""
    console.clear()
    _print_art()
    console.print(f"[bold]{title}[/bold]")
    if subtitle:
        console.print(f"[dim]{subtitle}[/dim]")
    console.print(f"[dim]{_t('Use Up/Down, Enter to select, Esc or q to go back.')}[/dim]\n")
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
    options: Sequence[MenuOption | ModelChoice],
) -> int:
    """Return the padded label column width (capped) for aligning descriptions."""
    labels = [option.label for option in options]
    return min(max((len(label) for label in labels), default=0) + 4, 42)


def _visible_option_window(
    *,
    total: int,
    selected_index: int,
    subtitle: str | None,
) -> tuple[int, int]:
    """Compute the ``(start, end)`` slice of options that fits on screen.

    Args:
        total: Total number of options.
        selected_index: Index of the currently highlighted option.
        subtitle: Subtitle line, if any (consumes one extra row).

    Returns:
        A half-open ``(start, end)`` range scrolled to keep the selection visible.
    """
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
    """Return the welcome art as ``(style_class, text)`` prompt_toolkit fragments."""
    fragments: list[tuple[str, str]] = []
    for line in WELCOME_ART.splitlines():
        style = "class:art.name" if "C I 2 L A B" in line else "class:art.gear"
        fragments.append((style, f"{line}\n"))
    return fragments


def _print_art() -> None:
    """Print the welcome art via the Rich console."""
    for line in WELCOME_ART.splitlines():
        style = "bold yellow" if "C I 2 L A B" in line else "bold blue"
        console.print(line, style=style)


def _ansi_art() -> str:
    """Return the welcome art as a raw ANSI-colored multi-line string."""
    lines = []
    for line in WELCOME_ART.splitlines():
        color = _ANSI_GOLD if "C I 2 L A B" in line else _ANSI_BLUE
        lines.append(f"{color}{line}{_ANSI_RESET}")
    return "\n".join(lines)


def _read_key() -> str:
    """Read a single normalized key press (``up``/``down``/``enter``/``escape``/``q``)."""
    if os.name == "nt":
        import msvcrt

        win_msvcrt: Any = msvcrt
        key = win_msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            key = win_msvcrt.getwch()
            return {"H": "up", "P": "down"}.get(key, "")
        return _normalize_key(key)
    return _read_posix_key()


def _read_posix_key() -> str:
    """Read one normalized key press from a POSIX terminal in raw mode."""
    import select
    import termios
    import tty

    # termios/tty are POSIX-only; aliasing them as Any lets this module
    # type-check on Windows too (this function only ever runs on POSIX).
    posix_termios: Any = termios
    posix_tty: Any = tty
    fd = sys.stdin.fileno()
    old = posix_termios.tcgetattr(fd)
    try:
        posix_tty.setraw(fd)
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
        posix_termios.tcsetattr(fd, posix_termios.TCSADRAIN, old)


def _normalize_key(key: str) -> str:
    """Map a raw character to a normalized key name, or ``""`` if unrecognized."""
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
    """Ensure a model is installed, optionally pulling it after confirmation.

    Args:
        choice: The selected model.

    Returns:
        ``True`` if the model is already installed or was pulled successfully,
        ``False`` if the user declined or the pull failed.
    """
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
    """Run ``ollama pull`` for a tag, returning its exit code (``1`` if missing)."""
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
    """Run ``ollama run`` for a tag, returning its exit code (``1`` if missing)."""
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
    """Echo and run a ``ci2lab`` command via ``runner``, then print a divider."""
    console.print(f"\n[bold]$[/bold] ci2lab {_format_args(args)}\n")
    try:
        return runner(args)
    finally:
        _print_divider()


def _run_doctor_with_ollama_install_option(runner: CommandRunner) -> int:
    """Run ``doctor`` and, if Ollama is missing, offer to install it.

    Returns:
        The doctor exit code, the installer exit code, or ``1`` if the installer
        command could not be found.
    """
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
    """Return True if an Ollama executable can be located on this machine."""
    return bool(ollama_install_info().get("executable"))


def _ollama_install_action() -> tuple[str, list[str]] | None:
    """Return a ``(label, command)`` to install Ollama, or None if unsupported.

    Picks ``winget`` on Windows or Homebrew on macOS when available.
    """
    if os.name == "nt" and shutil.which("winget"):
        return (
            "Windows Package Manager",
            ["winget", "install", "--id", "Ollama.Ollama", "-e"],
        )
    if sys.platform == "darwin" and shutil.which("brew"):
        return ("Homebrew", ["brew", "install", "--cask", "ollama"])
    return None


def _open_ollama_download_page() -> int:
    """Open the Ollama download page in a browser, printing the URL on failure."""
    try:
        webbrowser.open("https://ollama.com/download")
        return 0
    except Exception as exc:
        console.print(f"[yellow]Could not open the browser: {exc}[/yellow]")
        console.print("Download Ollama from: https://ollama.com/download")
        return 1
    finally:
        _print_divider()


def _confirm(message: str) -> bool:
    """Prompt with ``message`` and return True only for a yes/y answer."""
    return _prompt_text(message).strip().lower() in {"y", "yes"}


def _print_divider() -> None:
    """Print a dim horizontal rule to visually separate command output."""
    console.rule(style="dim")


def _command_mode(runner: CommandRunner) -> int:
    """Prompt for a raw ``ci2lab`` command line and run it via ``runner``."""
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
    """Split a command line into args (Windows-style), stripping outer quotes."""
    try:
        parts = shlex.split(line, posix=False)
    except ValueError as exc:
        console.print(f"[red]Could not parse command:[/red] {exc}")
        return []
    return [_strip_outer_quotes(part) for part in parts]


def _strip_outer_quotes(text: str) -> str:
    """Strip a single matching pair of surrounding single or double quotes."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _format_args(args: list[str]) -> str:
    """Format an argv list as a shell-like string, quoting args with spaces."""
    return " ".join(_quote_arg(arg) for arg in args)


def _quote_arg(arg: str) -> str:
    """Wrap an argument in double quotes (escaping inner quotes) if needed."""
    if not arg or any(char.isspace() for char in arg):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg


def _ask_text(label: str) -> str:
    """Prompt for a line of input labeled ``label`` and return it stripped."""
    return _prompt_text(f"{label}: ").strip()


def _pause() -> None:
    """Wait for the user to press Enter; ignore EOF/interrupt."""
    try:
        _prompt_text(f"\n{_t('Press Enter to return to the menu...')}")
    except (EOFError, KeyboardInterrupt):
        return


def _prompt_text(message: str) -> str:
    """Read a line of input, preferring prompt_toolkit and falling back to ``input``."""
    try:
        from prompt_toolkit import prompt
    except ImportError:
        return input(message)
    return prompt(message)


def _default_command_runner(args: list[str]) -> int:
    """Default :data:`CommandRunner` that dispatches back into the CLI ``main``."""
    from ci2lab.cli.main import main

    return main(args)


def _open_path(path: Path) -> None:
    """Open a file with the platform's default application.

    Raises:
        Exception: Propagates any OS error from the underlying open call.
    """
    if os.name == "nt":
        # os.startfile only exists on Windows; aliasing os as Any keeps this
        # cross-platform for the type checker without a platform-specific ignore.
        win_os: Any = os
        win_os.startfile(path)
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.run([opener, str(path)], check=True)


def _print_about() -> None:
    """Print a short description of what ci2lab is and how its chat modes differ."""
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
