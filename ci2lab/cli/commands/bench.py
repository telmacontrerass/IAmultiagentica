"""bench command."""

from __future__ import annotations

import argparse

from ci2lab.console import console


def _cmd_bench(args: argparse.Namespace) -> int:
    """Run performance benchmarks by translating CLI flags into bench-runner argv.

    Args:
        args: Parsed CLI arguments (``bench_command`` plus tasks dir, task ids,
            agents, model, samples, results dir and prices path).

    Returns:
        Process exit code from the benchmark runner, or ``0`` if no ``run`` was
        requested.
    """
    from ci2lab.bench.run import main as bench_main

    if getattr(args, "bench_command", None) != "run":
        console.print(
            "Usage: ci2lab bench run [--agent NAME ...] [--model TAG] "
            "[--samples N] [--task ID] [--tasks-dir PATH]"
        )
        return 0

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
