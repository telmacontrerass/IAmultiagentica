"""evals command."""

from __future__ import annotations

import argparse

from ci2lab.console import console


def _cmd_evals(args: argparse.Namespace) -> int:
    """Run harness evaluations by translating CLI flags into evals-runner argv.

    Args:
        args: Parsed CLI arguments (``evals_command`` plus tasks dir, task ids,
            model and the ``--live`` flag).

    Returns:
        Process exit code from the evals runner, or ``0`` if no ``run`` was
        requested.
    """
    from ci2lab.evals.run import main as evals_main

    if args.evals_command != "run":
        console.print("Usage: ci2lab evals run [--mock by default] [--live]")
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
