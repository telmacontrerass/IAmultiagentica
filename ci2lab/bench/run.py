"""CLI for the benchmark suite.

Usage:
  python -m ci2lab.bench.run --agent ci2lab
  ci2lab bench run --agent ci2lab --agent codex --model qwen2.5-coder:32b

Benchmarks always run live: ci2lab needs a local Ollama; ``claude-code`` and
``codex`` need their CLIs (under their subscriptions for H1, or ``--oss`` on the
shared model for H2). This never runs under pytest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ci2lab.bench.adapters import ADAPTER_NAMES
from ci2lab.bench.excel import write_report
from ci2lab.bench.report import load_records
from ci2lab.bench.runner import print_summary_table, run_bench_suite
from ci2lab.bench.task import default_tasks_dir
from ci2lab.console import console

REPORT_FILENAME = "benchmark_report.xlsx"

DEFAULT_BENCH_MODEL = "qwen2.5-coder:32b"


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark suite from the command line.

    Args:
        argv: Optional argument list. When ``None`` the process arguments are
            used.

    Returns:
        ``0`` on a completed run, ``1`` on a configuration error (no tasks /
        missing directory). A benchmark never "fails the build" on low scores.
    """
    parser = argparse.ArgumentParser(
        prog="ci2lab.bench.run",
        description="Performance benchmarks for the ci2lab harness vs Codex/Claude Code",
    )
    parser.add_argument("--tasks-dir", default=None, help="Directory with task JSON files")
    parser.add_argument(
        "--task", action="append", dest="task_ids", metavar="ID", help="Run only these tasks"
    )
    parser.add_argument(
        "--agent",
        action="append",
        dest="agents",
        choices=list(ADAPTER_NAMES),
        metavar="NAME",
        help=f"Conditions to run (repeatable): {', '.join(ADAPTER_NAMES)}",
    )
    parser.add_argument(
        "--model", default=DEFAULT_BENCH_MODEL, help="Model tag for ci2lab / codex --oss"
    )
    parser.add_argument("--samples", type=int, default=5, help="Samples per (task, agent)")
    parser.add_argument("--results-dir", default=None, help="Base directory for run artifacts")
    parser.add_argument("--prices", default=None, help="Path to the price table JSON")

    args = parser.parse_args(argv)
    agents = args.agents or ["ci2lab"]

    tasks_dir = Path(args.tasks_dir) if args.tasks_dir else default_tasks_dir()
    if not tasks_dir.is_dir():
        console.print(
            f"[red]Tasks directory not found:[/red] {tasks_dir}\n"
            "Create tasks under benchmarks/tasks/*.json or pass --tasks-dir."
        )
        return 1

    console.print(
        f"[bold]ci2lab benchmarks[/bold] — agents {agents} · "
        f"model [cyan]{args.model}[/cyan] · samples {args.samples}"
    )
    console.print("[dim]Live run: ci2lab needs Ollama; claude-code/codex need their CLIs.[/dim]\n")

    try:
        summary, _ = run_bench_suite(
            agents=agents,
            model=args.model,
            samples=args.samples,
            tasks_dir=tasks_dir,
            results_base=Path(args.results_dir) if args.results_dir else None,
            task_ids=args.task_ids,
            prices_path=Path(args.prices) if args.prices else None,
        )
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1

    print_summary_table(summary)
    console.print(f"\n[bold]Summary:[/bold] {summary.passed_runs}/{summary.total_runs} runs solved")
    console.print(f"[dim]Results: {summary.results_dir}[/dim]")
    _regenerate_report(Path(summary.results_dir))
    return 0


def _regenerate_report(run_dir: Path) -> None:
    """Refresh the aggregate Excel report from every valid run under the results base.

    Called after a run completes; scans the results base (the parent of this
    run's folder) so the workbook always reflects the full valid history. A
    reporting failure is logged but never fails the benchmark.

    Args:
        run_dir: The timestamped directory this run wrote its artifacts to.
    """
    results_base = run_dir.parent
    out_path = results_base / REPORT_FILENAME
    try:
        rows = load_records([results_base])
        written = write_report(rows, out_path)
    except Exception as exc:  # reporting must never break a run
        console.print(f"[yellow]Excel report skipped:[/yellow] {exc}")
        return
    if written is not None:
        console.print(f"[dim]Excel report: {written}[/dim]")


if __name__ == "__main__":
    sys.exit(main())
