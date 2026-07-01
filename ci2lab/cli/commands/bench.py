"""bench command."""

from __future__ import annotations

import argparse

from ci2lab.console import console


def _cmd_bench(args: argparse.Namespace) -> int:
    """Dispatch ``ci2lab bench`` subcommands (``run`` and ``report``).

    Args:
        args: Parsed CLI arguments (``bench_command`` plus its options).

    Returns:
        Process exit code from the benchmark runner/reporter, or ``0`` for the
        usage message.
    """
    command = getattr(args, "bench_command", None)
    if command == "report":
        from ci2lab.bench.report import main as report_main

        return report_main(list(args.paths or []))
    if command != "run":
        console.print(
            "Usage:\n"
            "  ci2lab bench run [--agent NAME ...] [--model TAG] [--samples N] [--task ID]\n"
            "  ci2lab bench report [PATH ...]"
        )
        return 0

    from ci2lab.bench.run import main as bench_main

    argv: list[str] = []
    if args.tasks_dir:
        argv.extend(["--tasks-dir", args.tasks_dir])
    for tid in args.task_ids or []:
        argv.extend(["--task", tid])
    for agent in args.agents or []:
        argv.extend(["--agent", agent])
    if args.model:
        argv.extend(["--model", args.model])
    if args.samples is not None:
        argv.extend(["--samples", str(args.samples)])
    if args.results_dir:
        argv.extend(["--results-dir", args.results_dir])
    if args.prices:
        argv.extend(["--prices", args.prices])
    return bench_main(argv)
