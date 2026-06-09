"""
CLI del sistema de evaluación del arnés.

Uso:
  python -m ci2lab.evals.run              # mock (sin Ollama)
  python -m ci2lab.evals.run --live       # requiere Ollama
  ci2lab evals run --mock
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console

from ci2lab.evals.runner import print_summary_table, run_eval_suite
from ci2lab.evals.task import default_tasks_dir

console = Console()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ci2lab.evals.run",
        description="Evaluación práctica del arnés Ci2Lab (tareas repetibles)",
    )
    parser.add_argument(
        "--tasks-dir",
        default=None,
        help="Directorio con tareas JSON (default: evals/tasks/)",
    )
    parser.add_argument(
        "--task",
        action="append",
        dest="task_ids",
        metavar="ID",
        help="Ejecutar solo estas tareas (repetible)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Tag Ollama (solo modo --live)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Usar Ollama real (por defecto: modo mock sin Ollama)",
    )

    args = parser.parse_args(argv)
    use_mock = not args.live

    tasks_dir = None
    if args.tasks_dir:
        from pathlib import Path

        tasks_dir = Path(args.tasks_dir)

    if tasks_dir is None:
        tasks_dir = default_tasks_dir()
    if not tasks_dir.is_dir():
        console.print(
            "[red]No se encontró el directorio de tareas.[/red]\n"
            f"  Esperado: {tasks_dir}\n\n"
            "Crea tareas en evals/tasks/*.json o pasa --tasks-dir."
        )
        return 1

    console.print(
        f"[bold]Ci2Lab evals[/bold] — modo "
        f"{'[cyan]mock[/cyan]' if use_mock else '[yellow]live[/yellow]'}"
    )
    if use_mock:
        console.print(
            "[dim]Sin Ollama. Usa --live para evaluar contra el modelo real.[/dim]\n"
        )
    else:
        console.print(
            "[dim]Requiere Ollama activo. Los prompts reales pueden variar.[/dim]\n"
        )

    try:
        summary, results = run_eval_suite(
            tasks_dir=tasks_dir,
            task_ids=args.task_ids,
            model=args.model,
            use_mock=use_mock,
        )
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1

    print_summary_table(results)
    console.print(
        f"\n[bold]Resumen:[/bold] {summary.passed}/{summary.total} PASS"
    )
    console.print(f"[dim]Resultados: {summary.results_dir}[/dim]")

    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
