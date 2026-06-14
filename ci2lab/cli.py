"""CLI principal de Ci2Lab."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys

from rich.console import Console
from rich.table import Table

from ci2lab.config import DEFAULT_TOOL_MODE, Ci2LabConfig, load_config, merge_cli_config
from ci2lab.harness.security_profiles import SecurityConfig, resolved_opencode_permissions
from ci2lab.contracts import HardwareProfile, ModelSpec
from ci2lab.hardware import scan_hardware
from ci2lab.router.catalog import load_model_catalog
from ci2lab.router.intent import classify_intent
from ci2lab.runtime.ollama import fetch_installed_model_names, is_catalog_model_installed
from ci2lab.router.recommend import (
    build_display_recommendations,
    recommend_download_plan,
    recommendation_pool_size,
    score_recommendations,
)

console = Console()

# Marcadores ASCII para salida compatible con consolas Windows (cp1252).
_DOCTOR_OK = "OK"
_DOCTOR_ERROR = "ERROR"
_DOCTOR_WARN = "WARN"

_CLI_COMMANDS = frozenset(
    {
        "agent",
        "chat",
        "sessions",
        "doctor",
        "hardware",
        "models",
        "evals",
        "permissions",
        "ui",
        "tools",
    }
)

_DOCUMENT_DEPENDENCIES = (
    ("pypdf", "PDF"),
    ("docx", "Word/DOCX"),
    ("pptx", "PowerPoint/PPTX"),
    ("openpyxl", "Excel/XLSX"),
)


def _is_global_help_request(raw_argv: list[str]) -> bool:
    """True cuando el usuario pide ayuda global sin subcomando."""
    if not raw_argv:
        return True
    return raw_argv in (["--help"], ["-h"])


def _print_global_help() -> None:
    """Ayuda global ASCII (compatible cp1252)."""
    lines = [
        "usage: ci2lab [opciones] [comando] [argumentos]",
        "",
        "CLI local: detecta hardware, recomienda modelos y ejecuta un agente",
        "con herramientas en terminal (read, grep, bash, edicion supervisada).",
        "",
        "Atajo:",
        '  ci2lab "peticion"                 Ejecuta el agente (equivale a agent)',
        "",
        "Comandos principales:",
        '  ci2lab agent "peticion"           Una tarea y sale',
        "  ci2lab chat                       Modo interactivo (REPL)",
        "  ci2lab tools qwen:1.8b            Chat sencillo con herramientas",
        "  ci2lab qwen:1.8b tools            Lo mismo, forma abreviada",
        "  ci2lab sessions [--json]          Lista sesiones guardadas",
        "  ci2lab doctor                     Comprueba Python, Ollama y modelos",
        "  ci2lab hardware [--json]          RAM, GPU, presupuesto de memoria",
        "  ci2lab models recommend [consulta]",
        "                                    Modelos recomendados para tu PC",
        "  ci2lab models install <modelo>    Comandos pull/run/chat para un modelo",
        "  ci2lab models run <modelo>        Abre el modelo con ollama run",
        "  ci2lab evals run                  Evaluaciones del arnes (mock)",
        "  ci2lab permissions summary        Dashboard de permisos / auditoria",
        "  ci2lab ui                         Interfaz web local",
        "",
        "Flags del agente (atajo, agent y chat):",
        "  --model TAG                       Tag Ollama (ej. qwen2.5-coder:7b)",
        "  --tool-mode {native,fenced}       native=function calling; fenced=bloques",
        "  --workspace PATH                  Directorio de trabajo del agente",
        "  --cwd PATH                        Alias legacy de --workspace",
        "  --yes                             Auto-confirmar bash (no omite preview)",
        "  --no-stream                       Desactivar streaming de tokens",
        "  --max-rounds N                    Maximo de vueltas del agente",
        "  --session ID                      Reanudar sesion en chat",
        "  --runs-dir PATH                   Directorio de logs (default: runs)",
        "  --no-log                          No guardar artefactos en runs/",
        "",
        "Importante: los flags del agente van ANTES del subcomando:",
        "  ci2lab --model qwen2.5-coder:7b --tool-mode fenced chat",
        "Atajo equivalente para uso normal:",
        "  ci2lab qwen:1.8b tools",
        "",
        "Opciones por comando:",
        "  models recommend [--json] [--limit N] [consulta]",
        "  models install <id|tag> [--json]",
        "  models run <id|tag>",
        "  evals run [--live] [--model TAG] [--task ID] [--tasks-dir PATH]",
        "",
        "Evals (alternativa):",
        "  python -m ci2lab.evals.run        Equivalente a ci2lab evals run (mock)",
        "",
        "Herramientas del agente (dentro de chat/agent):",
        "  read_document, read_file, ls, glob, grep, edit_file, write_file, notebook_edit,",
        "  bash, git_status, git_diff, todo_write, ask_user, web_fetch",
        "",
        "Config opcional: ci2lab.yaml o ~/.ci2lab/ci2lab.yaml",
        "  (model, workspace, runs_dir, write_tools_enabled, etc.)",
        "",
        "Ayuda detallada por comando:",
        "  ci2lab <comando> --help",
        "  ci2lab models recommend --help",
    ]
    print("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if _is_global_help_request(raw_argv):
        _print_global_help()
        return 0

    raw_argv = _expand_tools_shortcut(raw_argv)

    if raw_argv and not any(tok in _CLI_COMMANDS for tok in raw_argv):
        raw_argv = ["agent", *raw_argv]

    parser = argparse.ArgumentParser(
        prog="ci2lab",
        description="Agente local multi-modelo con arnés agéntico",
    )
    _add_agent_flags(parser)

    sub = parser.add_subparsers(dest="command")

    agent_p = sub.add_parser("agent", help="Una petición y salir")
    agent_p.add_argument("agent_prompt", help="Petición para el agente")
    _add_agent_flags(agent_p)

    sub.add_parser("chat", help="Modo interactivo REPL").set_defaults(command="chat")

    sessions_p = sub.add_parser("sessions", help="Listar sesiones guardadas")
    sessions_p.add_argument("--json", action="store_true")

    sub.add_parser("doctor", help="Comprobar entorno")

    hardware_p = sub.add_parser("hardware", help="Detecta las características del ordenador")
    hardware_p.add_argument("--json", action="store_true", help="Muestra la salida en JSON")

    models_p = sub.add_parser("models", help="Trabaja con modelos locales")
    models_sub = models_p.add_subparsers(dest="models_command", required=True)
    recommend_p = models_sub.add_parser("recommend", help="Recomienda modelos para descargar")
    recommend_p.add_argument("model_prompt", nargs="*", help="Consulta concreta opcional")
    recommend_p.add_argument("--json", action="store_true", help="Muestra la salida en JSON")
    recommend_p.add_argument("--limit", type=int, default=5, help="Número máximo de modelos")
    install_p = models_sub.add_parser(
        "install",
        help="Muestra el comando para instalar y abrir un modelo permitido",
    )
    install_p.add_argument("model", help="ID del catálogo o tag Ollama")
    install_p.add_argument("--json", action="store_true", help="Muestra la salida en JSON")
    run_p = models_sub.add_parser(
        "run",
        help="Abre el modelo en la consola con ollama run",
    )
    run_p.add_argument("model", help="ID del catálogo o tag Ollama")

    evals_p = sub.add_parser("evals", help="Evaluación práctica del arnés")
    evals_sub = evals_p.add_subparsers(dest="evals_command")
    evals_run = evals_sub.add_parser("run", help="Ejecutar tareas de evals/")
    evals_run.add_argument("--tasks-dir", default=None)
    evals_run.add_argument("--task", action="append", dest="task_ids", metavar="ID")
    evals_run.add_argument("--model", default=None)
    evals_run.add_argument("--live", action="store_true")

    from ci2lab.cli_permissions import add_permissions_parser

    add_permissions_parser(sub)

    ui_p = sub.add_parser("ui", help="Interfaz web local")
    ui_p.add_argument("--host", default="127.0.0.1", help="Host local")
    ui_p.add_argument("--port", type=int, default=8765, help="Puerto local")
    ui_p.add_argument("--no-open", action="store_true", help="No abrir navegador")

    args = parser.parse_args(raw_argv)

    try:
        runtime = _resolve_runtime_config(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.command == "agent":
        return _run_turn(args.agent_prompt, args, runtime)
    if args.command == "chat":
        return _run_repl(args, runtime)
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


def _add_agent_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--model",
        default=None,
        help="Tag Ollama (override; si no, config o CI2LAB_MODEL)",
    )
    p.add_argument(
        "--tool-mode",
        choices=["native", "fenced"],
        default=None,
        help="Modo de invocación de herramientas",
    )
    p.add_argument(
        "--cwd",
        default=None,
        help="Directorio de trabajo (legacy; preferir --workspace)",
    )
    p.add_argument(
        "--workspace",
        default=None,
        help="Directorio de trabajo del agente (alias semántico de --cwd)",
    )
    p.add_argument("--yes", action="store_true", help="Auto-confirmar tools peligrosas")
    p.add_argument(
        "--security-engine",
        choices=["ci2lab", "opencode_experimental", "claude_experimental"],
        default=None,
        help="Motor de seguridad (default: ci2lab). opencode_experimental es INSEGURO.",
    )
    p.add_argument("--no-stream", action="store_true", help="Desactivar streaming de tokens")
    p.add_argument("--max-rounds", type=int, default=None)
    p.add_argument("--session", default=None, help="ID de sesión (nueva si se omite en REPL)")
    p.add_argument(
        "--runs-dir",
        default=None,
        help="Directorio base para logs de ejecución (default: runs)",
    )
    p.add_argument(
        "--no-log",
        action="store_true",
        help="No guardar artefactos de la ejecución en runs/",
    )


def _resolve_runtime_config(args: argparse.Namespace) -> Ci2LabConfig:
    base = load_config()
    merged = merge_cli_config(
        base,
        model=args.model,
        tool_mode=args.tool_mode,
        max_rounds=args.max_rounds,
        workspace=args.workspace,
        cwd=args.cwd,
        no_stream=args.no_stream,
        auto_confirm=args.yes,
        runs_dir=args.runs_dir,
        no_log=args.no_log,
    )
    if args.security_engine is not None:
        from ci2lab.security.engine import normalize_security_engine

        engine = normalize_security_engine(args.security_engine)
        sec = merged.security
        merged = Ci2LabConfig(
            **{
                **merged.__dict__,
                "security": SecurityConfig(
                    profile=sec.profile,
                    engine=engine,
                    bash_timeout_seconds=sec.bash_timeout_seconds,
                    max_tool_output_chars=sec.max_tool_output_chars,
                    permission=sec.permission,
                ),
            }
        )
    return merged


def _build_config(
    runtime: Ci2LabConfig,
    args: argparse.Namespace,
    selection,
):
    from ci2lab.harness import AgentConfig
    from ci2lab.harness.run_logger import build_config_snapshot
    from ci2lab.settings import load_settings, ToolSettings

    cwd = runtime.workspace or os.getcwd()
    security_limits = runtime.security.resolved_limits()
    opencode_perms = resolved_opencode_permissions(
        runtime.security,
        root_permission=runtime.permission or None,
    )

    loaded_settings = load_settings(cwd)
    # Solo adjuntar si hay alguna regla activa; None desactiva el check en registry
    effective_settings: ToolSettings | None = (
        loaded_settings
        if (loaded_settings.allow or loaded_settings.deny)
        else None
    )

    agent_fields = dict(
        cwd=cwd,
        max_rounds=runtime.max_rounds,
        auto_confirm=runtime.auto_confirm,
        stream=runtime.stream,
        run_log_enabled=runtime.log_runs,
        runs_dir=runtime.runs_dir,
        write_tools_enabled=runtime.write_tools_enabled,
        require_diff_preview=runtime.require_diff_preview,
        security_profile=runtime.security.profile,
        security_engine=runtime.security.engine,
        opencode_permissions=opencode_perms,
        bash_timeout_seconds=security_limits.bash_timeout_seconds,
        max_tool_output_chars=security_limits.max_tool_output_chars,
        tool_settings=effective_settings,
    )
    base_agent = AgentConfig(**agent_fields)
    agent = AgentConfig(
        **agent_fields,
        session_id=args.session,
        config_snapshot=build_config_snapshot(
            runtime_fields={
                "model": runtime.model,
                "backend_url": runtime.backend_url,
                "tool_mode": runtime.tool_mode,
                "max_rounds": runtime.max_rounds,
                "workspace": cwd,
                "stream": runtime.stream,
                "auto_confirm": runtime.auto_confirm,
                "log_runs": runtime.log_runs,
                "runs_dir": runtime.runs_dir,
                "write_tools_enabled": runtime.write_tools_enabled,
                "require_diff_preview": runtime.require_diff_preview,
                "security_profile": runtime.security.profile,
                "security_engine": runtime.security.engine,
                "bash_timeout_seconds": security_limits.bash_timeout_seconds,
                "max_tool_output_chars": security_limits.max_tool_output_chars,
            },
            agent_config=base_agent,
            selection=selection,
        ),
    )
    return agent


def _tool_mode_override(runtime: Ci2LabConfig, args: argparse.Namespace) -> str | None:
    """CLI flag or yaml/env config override catalog; None means use catalog default."""
    if args.tool_mode is not None:
        return args.tool_mode
    if runtime.tool_mode != DEFAULT_TOOL_MODE:
        return runtime.tool_mode
    return None


def _resolve_selection(
    runtime: Ci2LabConfig,
    prompt: str,
    args: argparse.Namespace,
):
    from ci2lab.pipeline import prepare_session

    _, selection = prepare_session(
        prompt,
        force_model=runtime.model,
        tool_mode_override=_tool_mode_override(runtime, args),
        backend_url=runtime.backend_url,
        pull=False,
    )
    return selection


def _run_turn(prompt: str, args: argparse.Namespace, runtime: Ci2LabConfig) -> int:
    from ci2lab.harness import run_agent
    from ci2lab.harness.llm_errors import LLMError

    selection = _resolve_selection(runtime, prompt, args)
    config = _build_config(runtime, args, selection)
    _print_document_dependency_warning()

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
    _print_document_dependency_warning()
    try:
        run_repl(selection, config, session_id=args.session)
    except LLMError as exc:
        console.print(f"[red]{exc.user_message}[/red]")
        return exc.exit_code
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido.[/yellow]")
        return 130
    return 0


def _cmd_sessions(args: argparse.Namespace) -> int:
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


def _cmd_ui(args: argparse.Namespace, runtime: Ci2LabConfig) -> int:
    from ci2lab.ui import run_ui

    return run_ui(
        runtime,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
    )


def _cmd_evals(args: argparse.Namespace) -> int:
    from ci2lab.evals.run import main as evals_main

    if args.evals_command != "run":
        console.print("Uso: ci2lab evals run [--mock por defecto] [--live]")
        return 0
    argv: list[str] = []
    if args.tasks_dir:
        argv.extend(["--tasks-dir", args.tasks_dir])
    if args.task_ids:
        for tid in args.task_ids:
            argv.extend(["--task", tid])
    if args.model:
        argv.extend(["--model", args.model])
    if args.live:
        argv.append("--live")
    return evals_main(argv)


def _cmd_doctor(runtime: Ci2LabConfig) -> int:
    import httpx

    ok = True
    console.print("[bold]ci2lab doctor[/bold]\n")

    try:
        import ci2lab  # noqa: F401

        console.print(f"[green]{_DOCTOR_OK}[/green] Paquete ci2lab importable")
    except ImportError as exc:
        console.print(f"[red]{_DOCTOR_ERROR}[/red] ci2lab: {exc}")
        ok = False

    missing_document_deps = _missing_document_dependencies()
    if missing_document_deps:
        names = ", ".join(name for name, _label in missing_document_deps)
        console.print(
            f"[yellow]{_DOCTOR_WARN}[/yellow] Faltan librerias de documentos: {names}"
        )
        console.print('  Ejecuta: pip install -e ".[dev]"')
    else:
        labels = ", ".join(label for _name, label in _DOCUMENT_DEPENDENCIES)
        console.print(
            f"[green]{_DOCTOR_OK}[/green] Lectura de documentos disponible ({labels})"
        )

    base_url = runtime.backend_url.removesuffix("/v1").rstrip("/")
    try:
        r = httpx.get(f"{base_url}/api/tags", timeout=3.0)
        r.raise_for_status()
        models = [m.get("name") for m in r.json().get("models", [])]
        console.print(
            f"[green]{_DOCTOR_OK}[/green] Ollama en {base_url} ({len(models)} modelos)"
        )
        if models:
            console.print(f"  Ejemplos: {', '.join(models[:5])}")
        if runtime.model not in models and not any(
            m and m.startswith(runtime.model.split(":")[0]) for m in models
        ):
            console.print(
                f"[yellow]{_DOCTOR_WARN}[/yellow] Modelo configurado "
                f"`{runtime.model}` no aparece en la lista"
            )
    except Exception as exc:
        console.print(
            f"[yellow]{_DOCTOR_WARN}[/yellow] Ollama no responde en {base_url}: {exc}"
        )
        console.print("  Comprueba que Ollama esté abierto y que `ollama serve` esté corriendo.")

    return 0 if ok else 1


def _missing_document_dependencies() -> list[tuple[str, str]]:
    return [
        (module_name, label)
        for module_name, label in _DOCUMENT_DEPENDENCIES
        if importlib.util.find_spec(module_name) is None
    ]


def _print_document_dependency_warning() -> None:
    missing = _missing_document_dependencies()
    if not missing:
        return
    names = ", ".join(name for name, _label in missing)
    console.print(
        f"[yellow]{_DOCTOR_WARN}[/yellow] Faltan librerias para leer documentos: {names}"
    )
    console.print('  Ejecuta: pip install -e ".[dev]"')


def _cmd_hardware(args: argparse.Namespace) -> int:
    profile = scan_hardware()
    if args.json:
        console.print_json(json.dumps(profile.to_dict()))
        return 0

    table = Table(title="Caracteristicas detectadas")
    table.add_column("Dato")
    table.add_column("Valor")
    for key, value in profile.to_dict().items():
        display = str(value)
        if key == "memory_pressure":
            display = "True" if value else "False"
        table.add_row(key, display)
    console.print(table)
    return 0


def _print_memory_budget_context(profile: HardwareProfile) -> None:
    mode = profile.inference_mode
    console.print(
        f"Tu equipo permite teoricamente ~{profile.inference_budget_theoretical_gb:g} GB "
        f"para inferencia en modo {mode}."
    )
    if mode == "gpu" and profile.gpu_vendor != "apple":
        available_label = "VRAM disponible segura ahora"
    else:
        available_label = "RAM disponible segura ahora"
    console.print(
        f"{available_label}: ~{profile.inference_budget_available_gb:g} GB."
    )
    if profile.memory_pressure:
        console.print(
            "[yellow]Aviso: hay presion de memoria. "
            "Cierra aplicaciones antes de usar modelos grandes.[/yellow]"
        )


def _cmd_models_recommend(args: argparse.Namespace) -> int:
    profile = scan_hardware()
    prompt = " ".join(args.model_prompt)
    if prompt:
        return _focused_recommend_command(
            prompt=prompt,
            profile=profile,
            json_output=args.json,
            limit=args.limit,
        )
    return _download_plan_command(profile=profile, json_output=args.json)


def _cmd_models_install(args: argparse.Namespace) -> int:
    profile = scan_hardware()
    model = _resolve_allowed_model(args.model, profile=profile)
    if model is None:
        return 1

    commands = _install_commands(model)
    if args.json:
        console.print_json(json.dumps({
            "id": model.id,
            "display_name": model.display_name,
            "ollama_tag": model.ollama_tag,
            "commands": commands,
        }))
        return 0

    console.print(f"[bold]Modelo elegido:[/bold] {model.display_name}")
    console.print(f"[bold]Ollama:[/bold] {model.ollama_tag}\n")
    console.print("[bold]1. Instalar/descargar el modelo:[/bold]")
    console.print(f"  {commands['pull']}")
    console.print("\n[bold]2. Abrir chat directo con Ollama:[/bold]")
    console.print(f"  {commands['ollama_run']}")
    console.print("\n[bold]3. Abrir chat agéntico desde ci2lab:[/bold]")
    console.print(f"  {commands['ci2lab_chat']}")
    return 0


def _cmd_models_run(args: argparse.Namespace) -> int:
    profile = scan_hardware()
    model = _resolve_allowed_model(args.model, profile=profile)
    if model is None:
        return 1

    console.print(f"[bold]Abriendo:[/bold] {model.display_name} ({model.ollama_tag})")
    console.print("[dim]Sal con /bye o Ctrl+C.[/dim]\n")
    try:
        completed = subprocess.run(["ollama", "run", model.ollama_tag], check=False)
    except FileNotFoundError:
        console.print("[red]No encuentro el comando `ollama`.[/red]")
        console.print("Instala Ollama y después ejecuta:")
        console.print(f"  {_install_commands(model)['pull']}")
        return 1
    return completed.returncode


def _install_commands(model: ModelSpec) -> dict[str, str]:
    return {
        "pull": f"ollama pull {model.ollama_tag}",
        "ollama_run": f"ollama run {model.ollama_tag}",
        "ci2lab_chat": f"ci2lab --model {model.id} chat",
    }


def _resolve_allowed_model(model_name: str, *, profile: HardwareProfile) -> ModelSpec | None:
    normalized = model_name.strip().lower()
    models = load_model_catalog()
    exact = [
        model
        for model in models
        if normalized in {
            model.id.lower(),
            model.ollama_tag.lower(),
            model.display_name.lower(),
        }
    ]

    if not exact:
        console.print(f"[red]Modelo no reconocido:[/red] {model_name}")
        _print_allowed_models(profile)
        return None

    model = exact[0]
    if not _model_allowed(model, profile):
        console.print(f"[red]Ese modelo existe, pero no cabe en este equipo:[/red] {model.display_name}")
        console.print(
            "Presupuesto aproximado para inferencia: "
            f"[bold]{profile.inference_budget_gb:g} GB[/bold]."
        )
        _print_allowed_models(profile)
        return None

    return model


def _model_allowed(model: ModelSpec, profile: HardwareProfile) -> bool:
    if profile.inference_mode == "gpu" and profile.gpu_vendor != "apple":
        required_gb = model.vram_min_gb
    else:
        required_gb = model.ram_inference_gb
    return required_gb <= profile.inference_budget_gb


def _print_allowed_models(profile: HardwareProfile) -> None:
    allowed = [model for model in load_model_catalog() if _model_allowed(model, profile)]
    if not allowed:
        console.print("[yellow]No hay modelos del catálogo que quepan con este presupuesto.[/yellow]")
        return

    table = Table(title="Modelos permitidos en este equipo")
    table.add_column("Escribe esto")
    table.add_column("Ollama")
    table.add_column("Nombre")
    for model in allowed:
        table.add_row(model.id, model.ollama_tag, model.display_name)
    console.print(table)


def _focused_recommend_command(
    *,
    prompt: str,
    profile,
    json_output: bool,
    limit: int,
) -> int:
    intent = classify_intent(prompt)
    runtime = load_config()
    installed_names, ollama_error = fetch_installed_model_names(runtime.backend_url)
    pool = score_recommendations(
        prompt,
        profile=profile,
        limit=recommendation_pool_size(limit),
    )
    recommendations = build_display_recommendations(
        pool,
        installed_names,
        limit=limit,
    )

    if json_output:
        payload = {
            "hardware": profile.to_dict(),
            "intent": {
                "category": intent.category,
                "confidence": intent.confidence,
                "signals": intent.signals,
                "difficulty": intent.difficulty,
            },
            "ollama_error": ollama_error,
            "models": [
                {
                    "id": entry.item.model.id,
                    "display_name": entry.item.model.display_name,
                    "ollama_tag": entry.item.model.ollama_tag,
                    "reason": entry.item.reason,
                    "score": entry.item.total_score,
                    "fit_label": entry.item.fit_label,
                    "recommendation_status": entry.item.recommendation_status,
                    "theoretical_fit": entry.item.theoretical_fit,
                    "current_fit": entry.item.current_fit,
                    "requires_memory_cleanup": entry.item.requires_memory_cleanup,
                    "installed": entry.installed,
                    "installation_label": entry.installation_label,
                    "criteria": _criteria_payload(entry.item),
                }
                for entry in recommendations
            ],
        }
        console.print_json(json.dumps(payload))
        return 0

    console.print(f"Intencion detectada: [bold]{intent.category}[/bold]")
    _print_memory_budget_context(profile)
    if ollama_error:
        console.print(
            "[yellow]Aviso: no pude consultar Ollama para marcar modelos instalados.[/yellow]"
        )

    if not recommendations:
        console.print("[yellow]No hay modelos del catálogo que quepan con este presupuesto.[/yellow]")
        return 1

    table = Table(title="Modelos recomendados")
    table.add_column("Modelo")
    table.add_column("Ollama")
    table.add_column("Instalacion")
    table.add_column("Estado")
    table.add_column("Score")
    table.add_column("Memoria")
    table.add_column("Motivo")
    for entry in recommendations:
        item = entry.item
        install_label = (
            f"[green]{entry.installation_label}[/green]"
            if entry.installed
            else entry.installation_label
        )
        table.add_row(
            item.model.display_name,
            item.model.ollama_tag,
            install_label,
            item.fit_label,
            str(item.total_score),
            _memory_summary(item),
            item.reason,
        )
    console.print(table)
    return 0


def _download_plan_command(*, profile, json_output: bool) -> int:
    runtime = load_config()
    installed_names, ollama_error = fetch_installed_model_names(runtime.backend_url)
    plan = recommend_download_plan(profile=profile, installed_names=installed_names)

    if json_output:
        payload = {
            "hardware": profile.to_dict(),
            "ollama_error": ollama_error,
            "download_plan": [
                {
                    "use_cases": item.use_cases,
                    "id": item.recommendation.model.id,
                    "display_name": item.recommendation.model.display_name,
                    "ollama_tag": item.recommendation.model.ollama_tag,
                    "reason": item.recommendation.reason,
                    "score": item.recommendation.total_score,
                    "fit_label": item.recommendation.fit_label,
                    "recommendation_status": item.recommendation.recommendation_status,
                    "theoretical_fit": item.recommendation.theoretical_fit,
                    "current_fit": item.recommendation.current_fit,
                    "requires_memory_cleanup": item.recommendation.requires_memory_cleanup,
                    "installed": item.installed,
                    "installation_label": (
                        "Ya instalado" if item.installed else "Para descargar"
                    ),
                    "criteria": _criteria_payload(item.recommendation),
                }
                for item in plan
            ],
        }
        console.print_json(json.dumps(payload))
        return 0

    _print_memory_budget_context(profile)
    if ollama_error:
        console.print(
            "[yellow]Aviso: no pude consultar Ollama para marcar modelos instalados.[/yellow]"
        )

    if not plan:
        console.print("[yellow]No hay modelos del catálogo que quepan con este presupuesto.[/yellow]")
        return 1

    table = Table(title="Modelos recomendados para tu equipo")
    table.add_column("Usos")
    table.add_column("Modelo")
    table.add_column("Ollama")
    table.add_column("Instalacion")
    table.add_column("Estado")
    table.add_column("Score")
    table.add_column("Memoria")
    table.add_column("Motivo")
    for item in plan:
        recommendation = item.recommendation
        install_label = (
            "[green]Ya instalado[/green]" if item.installed else "Para descargar"
        )
        table.add_row(
            ", ".join(item.use_cases),
            recommendation.model.display_name,
            recommendation.model.ollama_tag,
            install_label,
            recommendation.fit_label,
            str(recommendation.total_score),
            _memory_summary(recommendation),
            recommendation.reason,
        )
    console.print(table)
    return 0


def _criteria_payload(item) -> dict[str, float | str | bool]:
    return {
        "quality": item.quality_score,
        "speed": item.speed_score,
        "fit": item.fit_score,
        "context": item.context_score,
        "memory_required_gb": item.memory_required_gb,
        "memory_budget_gb": item.memory_budget_gb,
        "remaining_memory_gb": item.remaining_memory_gb,
        "memory_usage_percent": item.memory_usage_percent,
        "memory_fit_status": item.memory_fit_status,
        "recommendation_status": item.recommendation_status,
        "theoretical_fit": item.theoretical_fit,
        "current_fit": item.current_fit,
        "requires_memory_cleanup": item.requires_memory_cleanup,
    }


def _memory_summary(item) -> str:
    return (
        f"usa ~{item.memory_required_gb:g} GB "
        f"({item.memory_usage_percent:g}%); "
        f"queda ~{item.remaining_memory_gb:g} GB"
    )


if __name__ == "__main__":
    sys.exit(main())
