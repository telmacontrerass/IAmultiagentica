"""CLI principal de Ci2Lab."""

from __future__ import annotations

import argparse
import json
import os
import sys

from rich.console import Console
from rich.table import Table

from ci2lab.hardware import scan_hardware
from ci2lab.router.intent import classify_intent
from ci2lab.router.recommend import recommend_download_plan, score_recommendations

console = Console()


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    commands = {"agent", "chat", "sessions", "doctor", "hardware", "models"}
    if raw_argv and raw_argv[0] not in commands and not raw_argv[0].startswith("-"):
        raw_argv = ["agent", *raw_argv]

    parser = argparse.ArgumentParser(
        prog="ci2lab",
        description="Agente local multi-modelo con arnés agéntico",
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

    hardware_p = sub.add_parser("hardware", help="Detecta las características del ordenador")
    hardware_p.add_argument("--json", action="store_true", help="Muestra la salida en JSON")

    models_p = sub.add_parser("models", help="Trabaja con modelos locales")
    models_sub = models_p.add_subparsers(dest="models_command", required=True)
    recommend_p = models_sub.add_parser("recommend", help="Recomienda modelos para descargar")
    recommend_p.add_argument("model_prompt", nargs="*", help="Consulta concreta opcional")
    recommend_p.add_argument("--json", action="store_true", help="Muestra la salida en JSON")
    recommend_p.add_argument("--limit", type=int, default=5, help="Número máximo de modelos")

    args = parser.parse_args(raw_argv)
    args.cwd = os.path.abspath(args.cwd or os.getcwd())

    if args.command == "agent":
        return _run_turn(args.agent_prompt, args)
    if args.command == "chat":
        return _run_repl(args)
    if args.command == "sessions":
        return _cmd_sessions(args)
    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "hardware":
        return _cmd_hardware(args)
    if args.command == "models" and args.models_command == "recommend":
        return _cmd_models_recommend(args)
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


def _cmd_hardware(args: argparse.Namespace) -> int:
    profile = scan_hardware()
    if args.json:
        console.print_json(json.dumps(profile.to_dict()))
        return 0

    table = Table(title="Características detectadas")
    table.add_column("Dato")
    table.add_column("Valor")
    for key, value in profile.to_dict().items():
        table.add_row(key, str(value))
    console.print(table)
    return 0


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


def _focused_recommend_command(
    *,
    prompt: str,
    profile,
    json_output: bool,
    limit: int,
) -> int:
    intent = classify_intent(prompt)
    recommendations = score_recommendations(prompt, profile=profile, limit=limit)

    if json_output:
        payload = {
            "hardware": profile.to_dict(),
            "intent": {
                "category": intent.category,
                "confidence": intent.confidence,
                "signals": intent.signals,
                "difficulty": intent.difficulty,
            },
            "models": [
                {
                    "id": item.model.id,
                    "display_name": item.model.display_name,
                    "ollama_tag": item.model.ollama_tag,
                    "reason": item.reason,
                    "score": item.total_score,
                    "criteria": _criteria_payload(item),
                }
                for item in recommendations
            ],
        }
        console.print_json(json.dumps(payload))
        return 0

    console.print(f"Intención detectada: [bold]{intent.category}[/bold]")
    console.print(
        "Tu equipo permite aproximadamente "
        f"[bold]{profile.inference_budget_gb:g} GB[/bold] para inferencia "
        f"en modo [bold]{profile.inference_mode}[/bold]."
    )

    if not recommendations:
        console.print("[yellow]No hay modelos del catálogo que quepan con este presupuesto.[/yellow]")
        return 1

    table = Table(title="Modelos recomendados")
    table.add_column("Modelo")
    table.add_column("Ollama")
    table.add_column("Score")
    table.add_column("Memoria")
    table.add_column("Por qué cabe")
    for item in recommendations:
        table.add_row(
            item.model.display_name,
            item.model.ollama_tag,
            str(item.total_score),
            _memory_summary(item),
            item.reason,
        )
    console.print(table)
    return 0


def _download_plan_command(*, profile, json_output: bool) -> int:
    plan = recommend_download_plan(profile=profile)

    if json_output:
        payload = {
            "hardware": profile.to_dict(),
            "download_plan": [
                {
                    "use_cases": item.use_cases,
                    "id": item.recommendation.model.id,
                    "display_name": item.recommendation.model.display_name,
                    "ollama_tag": item.recommendation.model.ollama_tag,
                    "reason": item.recommendation.reason,
                    "score": item.recommendation.total_score,
                    "criteria": _criteria_payload(item.recommendation),
                }
                for item in plan
            ],
        }
        console.print_json(json.dumps(payload))
        return 0

    console.print(
        "Tu equipo permite aproximadamente "
        f"[bold]{profile.inference_budget_gb:g} GB[/bold] para inferencia "
        f"en modo [bold]{profile.inference_mode}[/bold]."
    )

    if not plan:
        console.print("[yellow]No hay modelos del catálogo que quepan con este presupuesto.[/yellow]")
        return 1

    table = Table(title="Modelos sugeridos para descargar")
    table.add_column("Usos")
    table.add_column("Modelo")
    table.add_column("Ollama")
    table.add_column("Score")
    table.add_column("Memoria")
    table.add_column("Motivo")
    for item in plan:
        recommendation = item.recommendation
        table.add_row(
            ", ".join(item.use_cases),
            recommendation.model.display_name,
            recommendation.model.ollama_tag,
            str(recommendation.total_score),
            _memory_summary(recommendation),
            recommendation.reason,
        )
    console.print(table)
    return 0


def _criteria_payload(item) -> dict[str, float]:
    return {
        "quality": item.quality_score,
        "speed": item.speed_score,
        "fit": item.fit_score,
        "context": item.context_score,
        "memory_required_gb": item.memory_required_gb,
        "memory_budget_gb": item.memory_budget_gb,
        "remaining_memory_gb": item.remaining_memory_gb,
        "memory_usage_percent": item.memory_usage_percent,
    }


def _memory_summary(item) -> str:
    return (
        f"usa ~{item.memory_required_gb:g} GB "
        f"({item.memory_usage_percent:g}%); "
        f"queda ~{item.remaining_memory_gb:g} GB"
    )


if __name__ == "__main__":
    sys.exit(main())
