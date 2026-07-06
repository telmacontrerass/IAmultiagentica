"""Benchmark runner: orchestrate task × agent × sample and aggregate results.

For each run it provisions a fresh workspace, optionally takes a git baseline,
invokes the agent adapter, captures the agent's file changes, injects the hidden
oracle files, grades with the verifier, derives cost from tokens, and appends a
row to ``results.jsonl``. A ``summary.json`` with Pass@1 / Pass@k / mean tokens /
imputed USD / median latency is written at the end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.table import Table

from ci2lab.bench.adapters import AgentAdapter, get_adapter
from ci2lab.bench.gitutil import changed_paths, init_baseline
from ci2lab.bench.metrics import compute_cost_usd, load_prices, mean, median, pass_at_k
from ci2lab.bench.task import (
    BenchTask,
    default_results_dir,
    load_tasks,
    setup_workspace,
)
from ci2lab.bench.verifier import verify
from ci2lab.console import console

__all__ = ["BenchRunSummary", "run_bench_suite"]

DEFAULT_K_REPORT = 5


@dataclass
class BenchRunSummary:
    """Summary of one full benchmark run across all task × agent × sample."""

    started_at: str
    ended_at: str
    model: str
    agents: list[str]
    samples: int
    total_runs: int
    passed_runs: int
    results_dir: str
    by_task_agent: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the summary to a JSON-ready mapping."""
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "model": self.model,
            "agents": self.agents,
            "samples": self.samples,
            "total_runs": self.total_runs,
            "passed_runs": self.passed_runs,
            "results_dir": self.results_dir,
            "by_task_agent": self.by_task_agent,
        }


def run_bench_suite(
    *,
    agents: list[str],
    model: str,
    samples: int,
    tasks_dir: Path | None = None,
    results_base: Path | None = None,
    task_ids: list[str] | None = None,
    prices_path: Path | None = None,
) -> tuple[BenchRunSummary, list[dict[str, Any]]]:
    """Run the benchmark matrix and write run artifacts.

    Args:
        agents: Adapter/condition names to run (e.g. ``["ci2lab", "codex"]``).
        model: Model tag passed to ci2lab and to Codex ``--oss``; ignored by a
            CLI running its subscription default.
        samples: Samples per (task, agent); ``0`` falls back to each task's
            ``k_samples`` or 1.
        tasks_dir: Directory of task JSON files; defaults to ``benchmarks/tasks``.
        results_base: Base directory for artifacts; defaults to
            ``benchmarks/results``.
        task_ids: Optional subset of task ids to run.
        prices_path: Optional path to the price table.

    Returns:
        The :class:`BenchRunSummary` and the per-run records.

    Raises:
        ValueError: If no tasks match the selection.
    """
    tasks = load_tasks(tasks_dir, task_ids=task_ids)
    if not tasks:
        raise ValueError("No tasks to run")
    prices = load_prices(prices_path)

    started = datetime.now()
    stamp = started.strftime("%Y-%m-%d_%H%M%S")
    results_dir = (results_base or default_results_dir()) / stamp
    results_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_dir / "results.jsonl"

    records: list[dict[str, Any]] = []
    for task in tasks:
        k = samples if samples > 0 else (task.k_samples or 1)
        for agent_name in agents:
            adapter = get_adapter(agent_name)
            console.print(f"[bold]> {task.id}[/bold] · {agent_name} · {k} sample(s)")
            for sample in range(k):
                record = _run_one(
                    task,
                    adapter,
                    sample,
                    model=model,
                    results_dir=results_dir,
                    prices=prices,
                )
                records.append(record)
                with results_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                _print_run(record)

    ended = datetime.now()
    by_task_agent = _aggregate(records)
    summary = BenchRunSummary(
        started_at=started.isoformat(),
        ended_at=ended.isoformat(),
        model=model,
        agents=list(agents),
        samples=samples,
        total_runs=len(records),
        passed_runs=sum(1 for r in records if r["solved"]),
        results_dir=str(results_dir),
        by_task_agent=by_task_agent,
    )
    (results_dir / "summary.json").write_text(
        json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary, records


def _run_one(
    task: BenchTask,
    adapter: AgentAdapter,
    sample: int,
    *,
    model: str,
    results_dir: Path,
    prices: dict[str, Any],
) -> dict[str, Any]:
    """Provision, run, grade and score one (task, agent, sample)."""
    agent_name = adapter.name
    workspace = results_dir / "workspaces" / agent_name / task.id / f"s{sample}"
    runs_dir = results_dir / "runs" / agent_name / task.id / f"s{sample}"
    workspace.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    setup_workspace(workspace, task.workspace_setup)
    baseline = init_baseline(workspace) if task.git_baseline else False

    result = adapter.run(
        task, workspace, model=model, runs_dir=runs_dir, timeout=task.timeout_seconds
    )

    changed = changed_paths(workspace) if baseline else []
    if task.hidden_setup:
        setup_workspace(workspace, task.hidden_setup)

    verdict = verify(
        task,
        workspace=workspace,
        final_answer=result.final_answer,
        changed_paths=changed,
    )
    solved = verdict.solved and result.status not in {"error", "timeout"}

    if result.cost_usd is None:
        pricing_model = str(result.raw.get("model") or model)
        result.cost_usd = compute_cost_usd(
            result.prompt_tokens, result.completion_tokens, pricing_model, prices
        )

    record: dict[str, Any] = {
        "task_id": task.id,
        "task_name": task.name,
        "category": task.category,
        "agent": agent_name,
        "sample": sample,
        "solved": solved,
        "functional_success": verdict.solved,
        "failure_reasons": verdict.failure_reasons,
        "model": model,
        "workspace": str(workspace),
        **result.to_dict(),
    }
    record.update(
        _evidence_metrics(
            task,
            result=result,
            functional_success=verdict.solved,
            changed_paths=changed,
        )
    )
    return record


def _evidence_metrics(
    task: BenchTask,
    *,
    result: Any,
    functional_success: bool,
    changed_paths: list[str],
) -> dict[str, Any]:
    trace = _read_multiagent_trace(result.transcript_path)
    tool_entries = _tool_entries_from_artifacts(result.transcript_path, trace)
    tool_names = [str(entry.get("tool") or "") for entry in tool_entries]
    write_present = any(name in _WRITE_TOOLS for name in tool_names)
    readback_present = any(name in _READBACK_TOOLS for name in tool_names)
    scope_present = any(name in {"git_status", "git_diff"} for name in tool_names)
    expectations = task.evidence_expectations
    required_checks: list[bool] = []
    if expectations.get("write_evidence_present") is True:
        required_checks.append(write_present)
    if expectations.get("readback_evidence_present") is True:
        required_checks.append(readback_present)
    if expectations.get("scope_evidence_present") is True:
        required_checks.append(scope_present)
    evidence_success = all(required_checks) if required_checks else None
    failure = _failure_classification(trace)
    status = str(result.status or "")
    looks_successful = (
        status in {"success", "completed"} or "completed" in result.final_answer.lower()
    )
    false_positive = bool(
        looks_successful and (not functional_success or (evidence_success is False))
    )
    return {
        "evidence_success": evidence_success,
        "false_positive": false_positive,
        "write_evidence_present": write_present,
        "readback_evidence_present": readback_present,
        "scope_evidence_present": scope_present,
        "failure_classification": failure.get("failure_class") if failure else None,
        "failure_classification_detail": failure,
        "tool_violation_count": _tool_violation_count(tool_entries, trace),
        "changed_paths": changed_paths,
    }


_WRITE_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "apply_patch",
        "write_docx",
        "write_pptx",
        "docx_to_pdf",
        "notebook_edit",
    }
)
_READBACK_TOOLS = frozenset({"read_file", "read_document", "grep", "inspect_file"})


def _read_multiagent_trace(transcript_path: str | None) -> dict[str, Any]:
    if not transcript_path:
        return {}
    path = Path(transcript_path) / "multiagent_trace.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _tool_entries_from_artifacts(
    transcript_path: str | None,
    trace: dict[str, Any],
) -> list[dict[str, Any]]:
    if trace:
        entries: list[dict[str, Any]] = []
        for phase in trace.get("phases") or []:
            if not isinstance(phase, dict):
                continue
            role = str(phase.get("role") or "")
            for entry in phase.get("tool_calls") or []:
                if isinstance(entry, dict):
                    enriched = dict(entry)
                    enriched["role"] = role
                    entries.append(enriched)
        return entries
    if not transcript_path:
        return []
    path = Path(transcript_path) / "tool_calls.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _failure_classification(trace: dict[str, Any]) -> dict[str, Any]:
    value = trace.get("failure_classification")
    return value if isinstance(value, dict) else {}


def _tool_violation_count(tool_entries: list[dict[str, Any]], trace: dict[str, Any]) -> int:
    count = sum(
        1
        for entry in tool_entries
        if str(entry.get("outcome") or "")
        in {"blocked_by_skill", "blocked_by_config", "invalid_tool_via_bash", "role_violation"}
    )
    for phase in trace.get("phases") or []:
        if isinstance(phase, dict) and phase.get("status") in {
            "role_violation",
            "invalid_tool_via_bash",
        }:
            count += 1
    return count


def _aggregate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate per (task, agent): Pass@1, Pass@k, mean tokens/cost, latency."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault((record["task_id"], record["agent"]), []).append(record)

    rows: list[dict[str, Any]] = []
    for (task_id, agent), group in sorted(groups.items()):
        n = len(group)
        c = sum(1 for r in group if r["solved"])
        tokens = [float(r["total_tokens"]) for r in group if r["total_tokens"] is not None]
        costs = [float(r["cost_usd"]) for r in group if r["cost_usd"] is not None]
        latencies = [float(r["wall_clock_s"]) for r in group if r["wall_clock_s"] is not None]
        functional = sum(1 for r in group if r.get("functional_success"))
        evidence_values = [
            r.get("evidence_success") for r in group if r.get("evidence_success") is not None
        ]
        evidence = sum(1 for value in evidence_values if value)
        false_positives = sum(1 for r in group if r.get("false_positive"))
        tool_violations = sum(r.get("tool_violation_count") or 0 for r in group)
        rows.append(
            {
                "task_id": task_id,
                "agent": agent,
                "n": n,
                "solved": c,
                "pass_at_1": round(c / n, 4) if n else 0.0,
                "pass_at_k": round(pass_at_k(n, c, min(DEFAULT_K_REPORT, n)), 4),
                "functional_success_rate": round(functional / n, 4) if n else 0.0,
                "evidence_success_rate": (
                    round(evidence / len(evidence_values), 4) if evidence_values else None
                ),
                "false_positive_count": false_positives,
                "tool_violation_count": tool_violations,
                "mean_total_tokens": _opt_round(mean(tokens), 1),
                "mean_cost_usd": _opt_round(mean(costs), 6),
                "median_latency_s": _opt_round(median(latencies), 2),
            }
        )
    return rows


def _opt_round(value: float | None, digits: int) -> float | None:
    """Round ``value`` to ``digits`` places, passing ``None`` through."""
    return None if value is None else round(value, digits)


def _print_run(record: dict[str, Any]) -> None:
    """Print a one-line PASS/FAIL with key metrics for a single run."""
    status = "[green]PASS[/green]" if record["solved"] else "[red]FAIL[/red]"
    tokens = record["total_tokens"]
    latency = record["wall_clock_s"]
    console.print(
        f"    {status} s{record['sample']} "
        f"[dim]({record['status']}, {tokens} tok, {latency:.1f}s)[/dim]"
    )
    # Surface the agent's own error FIRST — when the agent errored, the oracle
    # failure reasons below are only the downstream symptom (the agent never ran,
    # so the fixture is unchanged and its tests "fail"). This is the real cause.
    if record.get("status") in {"error", "timeout"} and record.get("error"):
        console.print(f"      [bold red]! agent error:[/bold red] {str(record['error'])[:400]}")
    if not record["solved"]:
        for reason in record["failure_reasons"]:
            console.print(f"      [red]-[/red] {reason}")


def print_summary_table(summary: BenchRunSummary) -> None:
    """Render a Rich table of the per (task, agent) aggregates."""
    table = Table(title=f"Benchmark results · model {summary.model}")
    table.add_column("Task")
    table.add_column("Agent")
    table.add_column("Pass@1", justify="right")
    table.add_column("Pass@k", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("USD", justify="right")
    table.add_column("Latency", justify="right")
    table.add_column("ToolViol", justify="right")
    for row in summary.by_task_agent:
        table.add_row(
            row["task_id"],
            row["agent"],
            f"{row['pass_at_1']:.2f}",
            f"{row['pass_at_k']:.2f}",
            _fmt(row["mean_total_tokens"]),
            _fmt(row["mean_cost_usd"]),
            _fmt(row["median_latency_s"]),
            str(row.get("tool_violation_count", 0)),
        )
    console.print(table)


def _fmt(value: float | None) -> str:
    """Format an optional numeric aggregate for the summary table."""
    return "-" if value is None else f"{value:g}"
