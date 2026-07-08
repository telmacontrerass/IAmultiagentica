"""Isolated GLM possibility benchmark runner.

This runner intentionally writes only under ``glm_possibility_eval/results`` and
does not use ``benchmarks/results``. It reuses ci2lab's task loader and verifier,
but it builds the model selection directly so GLM can be served through either
Ollama or an OpenAI-compatible private endpoint such as vLLM/SGLang.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ci2lab.bench.gitutil import changed_paths, init_baseline
from ci2lab.bench.metrics import RunResult
from ci2lab.bench.task import BenchTask, load_tasks, setup_workspace
from ci2lab.bench.verifier import verify
from ci2lab.console import console
from ci2lab.harness import AgentConfig, run_agent
from ci2lab.harness.llm_errors import LLMError
from ci2lab.router.selection import build_model_selection

ROOT = Path(__file__).resolve().parent
DEFAULT_TASKS = ROOT / "tasks"
DEFAULT_RESULTS = ROOT / "results"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated GLM possibility evals.")
    parser.add_argument("--model", required=True, help="Model name served by the backend")
    parser.add_argument("--backend", choices=["ollama", "openai"], default="ollama")
    parser.add_argument("--backend-url", default=None)
    parser.add_argument("--tool-mode", choices=["fenced", "native"], default=None)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--tasks-dir", default=str(DEFAULT_TASKS))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS))
    parser.add_argument("--task", action="append", dest="task_ids", default=None)
    args = parser.parse_args(argv)

    tasks = load_tasks(Path(args.tasks_dir), task_ids=args.task_ids)
    if not tasks:
        console.print("[red]No tasks selected.[/red]")
        return 1

    started = datetime.now()
    run_dir = Path(args.results_dir) / started.strftime("%Y-%m-%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    selection = build_model_selection(
        args.model,
        backend=args.backend,
        backend_url=args.backend_url,
        tool_mode_override=args.tool_mode,
    )
    metadata = {
        "started_at": started.isoformat(),
        "model": args.model,
        "backend": args.backend,
        "backend_url": selection.backend_url,
        "tool_mode": selection.tool_mode,
        "selection": selection.to_dict(),
        "tasks_dir": str(Path(args.tasks_dir)),
        "samples": args.samples,
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    records: list[dict[str, Any]] = []
    results_path = run_dir / "results.jsonl"

    for task in tasks:
        for sample in range(args.samples):
            console.print(f"[bold]> {task.id}[/bold] · {args.model} · sample {sample}")
            record = run_one(task, sample, selection, run_dir)
            records.append(record)
            with results_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            status = "PASS" if record["solved"] else "FAIL"
            console.print(
                f"  {status} · {record['status']} · "
                f"{record['wall_clock_s']:.1f}s · reasons={record['failure_reasons']}"
            )

    summary = summarize(records, started, datetime.now(), run_dir, args.model)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    console.print(
        f"\n[bold]Summary:[/bold] {summary['passed_runs']}/{summary['total_runs']} solved"
    )
    console.print(f"[dim]Results: {run_dir}[/dim]")
    return 0


def run_one(task: BenchTask, sample: int, selection: Any, run_dir: Path) -> dict[str, Any]:
    workspace = run_dir / "workspaces" / task.id / f"s{sample}"
    runs_dir = run_dir / "runs" / task.id / f"s{sample}"
    workspace.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    setup_workspace(workspace, task.workspace_setup)
    baseline = init_baseline(workspace) if task.git_baseline else False

    config = AgentConfig(
        cwd=str(workspace),
        max_rounds=task.max_rounds,
        stream=False,
        auto_confirm=True,
        run_log_enabled=True,
        runs_dir=str(runs_dir),
        write_tools_enabled=task.write_tools_enabled
        if task.write_tools_enabled is not None
        else True,
        require_diff_preview=False,
        confirm_callback=lambda _name, _src: True,
        suppress_run_saved_message=True,
        security_engine="ci2lab",
        verify_completion=True,
    )

    status = "success"
    error = None
    final_answer = ""
    started = time.perf_counter()
    try:
        final_answer = run_agent(task.prompt, selection, config=config)
    except LLMError as exc:
        status = "error"
        error = exc.user_message
        final_answer = exc.user_message
    wall_clock_s = time.perf_counter() - started

    changed = changed_paths(workspace) if baseline else []
    if task.hidden_setup:
        setup_workspace(workspace, task.hidden_setup)
    verdict = verify(
        task,
        workspace=workspace,
        final_answer=final_answer,
        changed_paths=changed,
    )

    usage = config.token_usage.session
    result = RunResult(
        final_answer=final_answer,
        status=status,
        wall_clock_s=wall_clock_s,
        prompt_tokens=usage.prompt_tokens if usage.available else None,
        completion_tokens=usage.completion_tokens if usage.available else None,
        total_tokens=usage.total_tokens if usage.available else None,
        error=error,
        raw={"model": usage.model or selection.ollama_tag},
    )

    solved = verdict.solved and status != "error"
    return {
        "task_id": task.id,
        "task_name": task.name,
        "category": task.category,
        "sample": sample,
        "model": selection.ollama_tag,
        "backend": selection.backend,
        "tool_mode": selection.tool_mode,
        "solved": solved,
        "functional_success": verdict.solved,
        "failure_reasons": verdict.failure_reasons,
        "changed_paths": changed,
        "workspace": str(workspace),
        **result.to_dict(),
    }


def summarize(
    records: list[dict[str, Any]],
    started: datetime,
    ended: datetime,
    run_dir: Path,
    model: str,
) -> dict[str, Any]:
    by_task: dict[str, dict[str, Any]] = {}
    for record in records:
        entry = by_task.setdefault(
            record["task_id"],
            {"task_id": record["task_id"], "runs": 0, "solved": 0},
        )
        entry["runs"] += 1
        entry["solved"] += int(bool(record["solved"]))

    return {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "model": model,
        "total_runs": len(records),
        "passed_runs": sum(1 for record in records if record["solved"]),
        "pass_rate": (
            sum(1 for record in records if record["solved"]) / len(records)
            if records
            else 0
        ),
        "results_dir": str(run_dir),
        "by_task": list(by_task.values()),
    }


if __name__ == "__main__":
    raise SystemExit(main())
