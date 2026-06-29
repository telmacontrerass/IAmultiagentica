"""Evaluation task execution."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from rich.table import Table

from ci2lab.console import console
from ci2lab.evals.task import (
    CheckResult,
    EvalTask,
    TaskEvalResult,
    default_results_dir,
    evaluate_task,
    load_tasks,
    load_tool_calls_jsonl,
    setup_workspace,
)
from ci2lab.harness import AgentConfig, default_selection, run_agent
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.llm_errors import LLMError


@dataclass
class EvalRunSummary:
    """Summary metadata for one full evaluation run across all tasks."""

    started_at: str
    ended_at: str
    mode: str
    model: str
    total: int
    passed: int
    failed: int
    results_dir: str

    def to_dict(self) -> dict[str, Any]:
        """Serialise the run summary to a JSON-ready dict."""
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "mode": self.mode,
            "model": self.model,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "results_dir": self.results_dir,
        }


def _mock_responses_to_llm(
    responses: list[dict[str, Any]],
) -> list[LLMResponse]:
    """Convert mock response dicts into :class:`LLMResponse` objects for patching."""
    return [
        LLMResponse(
            content=item.get("content") or "",
            tool_calls=list(item.get("tool_calls") or []),
        )
        for item in responses
    ]


def _find_latest_run_dir(runs_parent: Path) -> Path | None:
    """Return the most recently modified subdirectory, or ``None`` if none exist."""
    if not runs_parent.is_dir():
        return None
    dirs = [p for p in runs_parent.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def _build_agent_config(
    task: EvalTask,
    workspace: Path,
    runs_dir: Path,
) -> AgentConfig:
    """Build the :class:`AgentConfig` used to run a single eval task.

    Maps the task's ``requires_approval`` and ``write_tools_enabled`` flags onto
    the harness configuration and pins non-interactive, logged execution under
    ``runs_dir`` with the ``ci2lab`` security engine.
    """
    confirm_callback: Callable[[str, str], bool] | None = None
    if task.requires_approval is False:
        confirm_callback = lambda _n, _s: False  # noqa: E731
    elif task.requires_approval is True:
        confirm_callback = lambda _n, _s: True  # noqa: E731

    write_enabled = task.write_tools_enabled if task.write_tools_enabled is not None else True

    return AgentConfig(
        cwd=str(workspace),
        max_rounds=task.max_rounds,
        stream=False,
        auto_confirm=task.auto_confirm,
        run_log_enabled=True,
        runs_dir=str(runs_dir),
        write_tools_enabled=write_enabled,
        require_diff_preview=True,
        confirm_callback=confirm_callback,
        security_engine="ci2lab",
    )


def run_single_task(
    task: EvalTask,
    *,
    workspace: Path,
    task_runs_dir: Path,
    model: str,
    use_mock: bool,
) -> TaskEvalResult:
    """Execute one task end-to-end and grade the result.

    Sets up the workspace, runs the agent (against mocked LLM responses when
    ``use_mock`` is true, otherwise live), loads the resulting tool-call log and
    grades it via :func:`evaluate_task`.

    Args:
        task: The task to run.
        workspace: Directory the agent operates in.
        task_runs_dir: Directory where the harness writes per-run logs.
        model: Ollama model tag (used in live mode).
        use_mock: When true, drive the agent with ``task.mock_responses``
            instead of a real model.

    Returns:
        The graded :class:`TaskEvalResult`, including any agent error.
    """
    setup_workspace(workspace, task.workspace_setup)
    config = _build_agent_config(task, workspace, task_runs_dir)
    selection = default_selection(model)

    if use_mock and not task.mock_responses:
        return TaskEvalResult(
            task_id=task.id,
            task_name=task.name,
            passed=False,
            checks=[
                CheckResult(
                    name="mock_responses",
                    check_type="configuration",
                    passed=False,
                    detail="The task does not define mock_responses",
                )
            ],
            tools_used=[],
            tool_outcomes=[],
            final_answer="",
            workspace=str(workspace),
            run_log_dir=None,
            error="mock required but no mock_responses",
        )

    final_answer = ""
    error: str | None = None

    # Silence all agent output during the task (shared console).
    quiet_console = patch("ci2lab.console.console.print")
    try:
        if use_mock:
            responses = _mock_responses_to_llm(task.mock_responses)
            with quiet_console:
                with patch("ci2lab.harness.query.loop.LLMClient") as mock_cls:
                    mock_cls.return_value.chat.side_effect = responses
                    final_answer = run_agent(task.prompt, selection, config=config)
        else:
            with quiet_console:
                final_answer = run_agent(task.prompt, selection, config=config)
    except LLMError as exc:
        error = exc.user_message
        final_answer = exc.user_message

    run_log_dir = _find_latest_run_dir(task_runs_dir)
    tool_calls = load_tool_calls_jsonl(run_log_dir / "tool_calls.jsonl") if run_log_dir else []

    result = evaluate_task(
        task,
        workspace=workspace,
        tool_calls=tool_calls,
        final_answer=final_answer,
    )
    result.run_log_dir = str(run_log_dir) if run_log_dir else None
    result.error = error
    if error:
        result.checks.append(
            CheckResult(
                check_type="agent_error",
                name="agent_error",
                passed=False,
                detail=error,
            )
        )
        result.passed = False
    return result


def run_eval_suite(
    *,
    tasks_dir: Path | None = None,
    results_base: Path | None = None,
    task_ids: list[str] | None = None,
    model: str | None = None,
    use_mock: bool = True,
) -> tuple[EvalRunSummary, list[TaskEvalResult]]:
    """Run every selected task and write run artifacts to a timestamped directory.

    For each task this creates an isolated workspace and run-log directory,
    executes and grades it, prints progress, and appends the result to
    ``results.jsonl``. A ``summary.json`` is written at the end.

    Args:
        tasks_dir: Directory of task JSON files; defaults to the standard path.
        results_base: Base directory for run artifacts; defaults to the
            standard results directory.
        task_ids: Optional subset of task ids to run.
        model: Ollama model tag; defaults to ``DEFAULT_MODEL``.
        use_mock: Run with mocked LLM responses when true.

    Returns:
        A tuple of the run :class:`EvalRunSummary` and the per-task results.

    Raises:
        ValueError: If no tasks match the selection.
    """
    from ci2lab.config import DEFAULT_MODEL

    tasks = load_tasks(tasks_dir, task_ids=task_ids)
    if not tasks:
        raise ValueError("No tasks to run")

    model_tag = model or DEFAULT_MODEL
    started = datetime.now()
    stamp = started.strftime("%Y-%m-%d_%H%M%S")
    results_dir = (results_base or default_results_dir()) / stamp
    results_dir.mkdir(parents=True, exist_ok=True)

    mode = "mock" if use_mock else "live"
    results: list[TaskEvalResult] = []

    for task in tasks:
        workspace = results_dir / "workspaces" / task.id
        workspace.mkdir(parents=True, exist_ok=True)
        task_runs = results_dir / "runs" / task.id
        task_runs.mkdir(parents=True, exist_ok=True)

        console.print(f"[bold]> {task.id}[/bold] {task.name}")
        result = run_single_task(
            task,
            workspace=workspace,
            task_runs_dir=task_runs,
            model=model_tag,
            use_mock=use_mock,
        )

        status = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
        console.print(f"  {status}")
        if not result.passed:
            for reason in result.failure_reasons:
                console.print(f"    [red]-[/red] {reason}")
        results.append(result)

        with (results_dir / "results.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")

    ended = datetime.now()
    passed = sum(1 for r in results if r.passed)
    summary = EvalRunSummary(
        started_at=started.isoformat(),
        ended_at=ended.isoformat(),
        mode=mode,
        model=model_tag,
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        results_dir=str(results_dir),
    )
    (results_dir / "summary.json").write_text(
        json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary, results


def print_summary_table(results: list[TaskEvalResult]) -> None:
    """Render a Rich table of task results (id, status, tools) to the console."""
    table = Table(title="Eval results")
    table.add_column("Task")
    table.add_column("Status")
    table.add_column("Tools")
    for row in results:
        state = "PASS" if row.passed else "FAIL"
        style = "green" if row.passed else "red"
        table.add_row(
            row.task_id,
            f"[{style}]{state}[/{style}]",
            ", ".join(row.tools_used) or "-",
        )
    console.print(table)
