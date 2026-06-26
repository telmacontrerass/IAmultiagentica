"""
CLI for the harness evaluation system.

Usage:
  python -m ci2lab.evals.run              # mock (without Ollama)
  python -m ci2lab.evals.run --live       # requires Ollama
  ci2lab evals run --mock
"""

from __future__ import annotations

import argparse
import sys

from ci2lab.console import console
from ci2lab.evals.runner import print_summary_table, run_eval_suite
from ci2lab.evals.task import default_tasks_dir


def main(argv: list[str] | None = None) -> int:
    """Run the harness evaluation suite from the command line.

    Args:
        argv: Optional command-line arguments. When ``None`` the process
            arguments (``sys.argv``) are used.

    Returns:
        A process exit code: ``0`` when every task passed (and the tasks
        directory was found), ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="ci2lab.evals.run",
        description="Practical evaluation of the Ci2Lab harness (repeatable tasks)",
    )
    parser.add_argument(
        "--tasks-dir",
        default=None,
        help="Directory with JSON tasks (default: evals/tasks/)",
    )
    parser.add_argument(
        "--task",
        action="append",
        dest="task_ids",
        metavar="ID",
        help="Run only these tasks (repeatable)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Ollama tag (only in --live mode)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use a real Ollama (default: mock mode without Ollama)",
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
            "[red]Tasks directory not found.[/red]\n"
            f"  Expected: {tasks_dir}\n\n"
            "Create tasks in evals/tasks/*.json or pass --tasks-dir."
        )
        return 1

    console.print(
        f"[bold]Ci2Lab evals[/bold] — mode "
        f"{'[cyan]mock[/cyan]' if use_mock else '[yellow]live[/yellow]'}"
    )
    if use_mock:
        console.print("[dim]No Ollama. Use --live to evaluate against the real model.[/dim]\n")
    else:
        console.print("[dim]Requires Ollama running. Real prompts may vary.[/dim]\n")

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
    console.print(f"\n[bold]Summary:[/bold] {summary.passed}/{summary.total} PASS")
    console.print(f"[dim]Results: {summary.results_dir}[/dim]")

    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
