"""Aggregate benchmark run artifacts into comparison tables and a validity report.

Reads the ``results.jsonl`` files written by ``ci2lab bench run`` (across one or
more run folders) and prints:

- a per (task, agent) table (Pass@1, Pass@5, tokens, USD, latency, errors, FPs);
- a per-agent rollup (macro Pass@1, error rate, false-positive rate);
- **validity warnings** that flag results you should not trust yet — error/timeout
  statuses, successful runs with no token count, false positives, and near-uniform
  token usage across different tasks (a tell-tale of an agent not actually using
  tools).

Usage:
  ci2lab bench report                     # all runs under benchmarks/results
  ci2lab bench report <dir-or-file> ...   # only these run folders / results.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rich.table import Table

from ci2lab.bench.metrics import (
    format_optional_number,
    is_number,
    mean,
    median,
    optional_round,
    pass_at_k,
)
from ci2lab.bench.task import default_results_dir
from ci2lab.console import console

__all__ = [
    "aggregate_by_agent",
    "aggregate_by_task_agent",
    "load_records",
    "main",
    "validity_warnings",
]

_K_REPORT = 5
_ERROR_STATUSES = {"error", "timeout"}


def load_records(paths: list[Path]) -> list[dict[str, Any]]:
    """Load result rows from ``results.jsonl`` files or directories containing them.

    Args:
        paths: Result directories (scanned recursively for ``results.jsonl``) or
            direct ``results.jsonl`` file paths.

    Returns:
        All parsed run records across the given paths.
    """
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("**/results.jsonl")))
        elif path.is_file():
            files.append(path)
    rows: list[dict[str, Any]] = []
    for file in files:
        for line in file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def aggregate_by_task_agent(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate rows into one summary per (task, agent)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("agent", "")), str(row.get("task_id", "")))
        groups.setdefault(key, []).append(row)
    return [_summarize(agent, task, group) for (agent, task), group in sorted(groups.items())]


def aggregate_by_agent(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate into one rollup per agent (macro-averaged over its tasks)."""
    per_task = aggregate_by_task_agent(rows)
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for row in per_task:
        by_agent.setdefault(str(row["agent"]), []).append(row)

    out: list[dict[str, Any]] = []
    for agent, task_rows in sorted(by_agent.items()):
        runs = sum(int(r["n"]) for r in task_rows)
        solved = sum(int(r["solved"]) for r in task_rows)
        errors = sum(int(r["errors"]) for r in task_rows)
        fps = sum(int(r["false_positives"]) for r in task_rows)
        macro_p1 = mean([float(r["pass_at_1"]) for r in task_rows]) or 0.0
        out.append(
            {
                "agent": agent,
                "tasks": len(task_rows),
                "runs": runs,
                "solved": solved,
                "macro_pass_at_1": round(macro_p1, 4),
                "error_rate": round(errors / runs, 3) if runs else 0.0,
                "false_positive_rate": round(fps / runs, 3) if runs else 0.0,
            }
        )
    return out


def validity_warnings(rows: list[dict[str, Any]]) -> list[str]:
    """Flag results that should not be trusted yet, grouped per agent."""
    warnings: list[str] = []
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_agent.setdefault(str(row.get("agent", "")), []).append(row)

    for agent, group in sorted(by_agent.items()):
        n = len(group)
        errors = sum(1 for r in group if r.get("status") in _ERROR_STATUSES)
        if errors:
            warnings.append(
                f"{agent}: {errors}/{n} runs errored/timed out — the CLI is not "
                "executing correctly (check the *_cmd.txt / *_stderr.txt in the run dir)."
            )
        null_tokens = sum(
            1 for r in group if r.get("status") == "success" and r.get("total_tokens") is None
        )
        if null_tokens:
            warnings.append(
                f"{agent}: {null_tokens}/{n} successful runs have no token count — "
                "telemetry parsing may not match this CLI's output."
            )
        fps = sum(1 for r in group if r.get("false_positive") is True)
        if fps:
            warnings.append(
                f"{agent}: {fps}/{n} runs flagged false_positive — the agent appeared "
                "to finish but failed the oracle."
            )
        warnings.extend(_uniform_token_warning(agent, group))
    return warnings


def _summarize(agent: str, task: str, group: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize one (task, agent) group of run rows."""
    n = len(group)
    solved = sum(1 for r in group if r.get("solved") is True)
    tokens = [float(r["total_tokens"]) for r in group if is_number(r.get("total_tokens"))]
    costs = [float(r["cost_usd"]) for r in group if is_number(r.get("cost_usd"))]
    latencies = [float(r["wall_clock_s"]) for r in group if is_number(r.get("wall_clock_s"))]
    return {
        "agent": agent,
        "task_id": task,
        "n": n,
        "solved": solved,
        "pass_at_1": round(solved / n, 4) if n else 0.0,
        "pass_at_k": round(pass_at_k(n, solved, min(_K_REPORT, n)), 4),
        "mean_total_tokens": optional_round(mean(tokens), 1),
        "mean_cost_usd": optional_round(mean(costs), 6),
        "median_latency_s": optional_round(median(latencies), 2),
        "errors": sum(1 for r in group if r.get("status") in _ERROR_STATUSES),
        "false_positives": sum(1 for r in group if r.get("false_positive") is True),
    }


def _uniform_token_warning(agent: str, group: list[dict[str, Any]]) -> list[str]:
    """Warn when token usage barely varies across different tasks (no real work)."""
    by_task: dict[str, list[float]] = {}
    for row in group:
        value = row.get("total_tokens")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            by_task.setdefault(str(row.get("task_id", "")), []).append(float(value))
    task_means = [m for m in (mean(v) for v in by_task.values()) if m is not None]
    if len(task_means) < 3:
        return []
    lo, hi = min(task_means), max(task_means)
    if hi > 0 and (hi - lo) / hi < 0.1:
        avg = mean(task_means) or 0.0
        return [
            f"{agent}: token usage is near-uniform (~{int(avg)}) across "
            f"{len(task_means)} different tasks — the agent may not be using tools "
            "(answering from the prompt instead of reading/writing files)."
        ]
    return []


def _print_task_agent_table(rows: list[dict[str, Any]]) -> None:
    """Render the per (task, agent) comparison table."""
    table = Table(title="Per task × agent")
    for column in (
        "Task",
        "Agent",
        "n",
        "Pass@1",
        "Pass@5",
        "Tokens",
        "USD",
        "Latency",
        "Err",
        "FP",
    ):
        table.add_column(column, justify="right" if column not in ("Task", "Agent") else "left")
    for row in rows:
        table.add_row(
            str(row["task_id"]),
            str(row["agent"]),
            str(row["n"]),
            f"{row['pass_at_1']:.2f}",
            f"{row['pass_at_k']:.2f}",
            format_optional_number(row["mean_total_tokens"]),
            format_optional_number(row["mean_cost_usd"]),
            format_optional_number(row["median_latency_s"]),
            str(row["errors"]),
            str(row["false_positives"]),
        )
    console.print(table)


def _print_agent_table(rows: list[dict[str, Any]]) -> None:
    """Render the per-agent rollup table."""
    table = Table(title="Per agent (macro-averaged over tasks)")
    for column in ("Agent", "Tasks", "Runs", "Pass@1", "ErrRate", "FPRate"):
        table.add_column(column, justify="right" if column != "Agent" else "left")
    for row in rows:
        table.add_row(
            str(row["agent"]),
            str(row["tasks"]),
            str(row["runs"]),
            f"{row['macro_pass_at_1']:.2f}",
            f"{row['error_rate']:.2f}",
            f"{row['false_positive_rate']:.2f}",
        )
    console.print(table)


def _print_warnings(warnings: list[str]) -> None:
    """Print the validity-warnings section."""
    if not warnings:
        console.print("[green]No validity warnings — all runs look trustworthy.[/green]")
        return
    console.print("\n[bold yellow]⚠ Validity warnings[/bold yellow]")
    for warning in warnings:
        console.print(f"  [yellow]-[/yellow] {warning}")


def main(argv: list[str] | None = None) -> int:
    """Aggregate benchmark results and print the comparison + validity report.

    Args:
        argv: Optional argument list; when ``None`` the process arguments are used.

    Returns:
        ``0`` when results were found and reported, ``1`` when none were found.
    """
    parser = argparse.ArgumentParser(
        prog="ci2lab.bench.report",
        description="Aggregate benchmark results into comparison tables + a validity report",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="results.jsonl files or run dirs (default: all under benchmarks/results)",
    )
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.paths] if args.paths else [default_results_dir()]
    rows = load_records(paths)
    if not rows:
        console.print("[yellow]No benchmark results found.[/yellow] Run `ci2lab bench run` first.")
        return 1

    _print_task_agent_table(aggregate_by_task_agent(rows))
    _print_agent_table(aggregate_by_agent(rows))
    _print_warnings(validity_warnings(rows))
    console.print(f"\n[dim]{len(rows)} runs aggregated from {len(paths)} path(s).[/dim]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
