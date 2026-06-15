"""ArgumentParser y ayuda global del CLI."""

from __future__ import annotations

import argparse

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
        "  --security-engine ENGINE          Motor: claude_experimental (default),",
        "                                    ci2lab (legacy), opencode_experimental (lab)",
        "  --no-stream                       Desactivar streaming de tokens",
        "  --max-rounds N                    Maximo de vueltas del agente",
        "  --session ID                      Reanudar sesion en chat",
        "  --runs-dir PATH                   Directorio de logs (default: runs)",
        "  --no-log                          No guardar artefactos en runs/",
        "",
        "Importante: los flags del agente van ANTES del subcomando:",
        "  ci2lab --model qwen2.5-coder:7b --tool-mode fenced chat",
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
    from ci2lab.security.engine import CLI_SECURITY_ENGINE_CHOICES

    p.add_argument(
        "--security-engine",
        choices=list(CLI_SECURITY_ENGINE_CHOICES),
        default=None,
        metavar="ENGINE",
        help=(
            "Motor de seguridad (default: claude_experimental). "
            "ci2lab=legacy sin deny/ask/allow; opencode_experimental=lab inseguro."
        ),
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


def build_parser() -> argparse.ArgumentParser:
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

    return parser
