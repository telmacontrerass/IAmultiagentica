"""In-process adapter for the ci2lab harness (single- and multi-agent).

Drives ``run_agent`` / ``run_multi_agent`` directly, which gives the richest
telemetry: token counts come from ``config.token_usage`` after the call, and
tool-call counts / rounds / status come from the run log the harness writes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from ci2lab.bench.metrics import (
    STATUS_ERROR,
    STATUS_SUCCESS,
    RunResult,
)
from ci2lab.bench.task import BenchTask
from ci2lab.evals.task import load_tool_calls_jsonl

__all__ = ["Ci2labAdapter"]

_RUN_STATUS_MAP = {
    "success": STATUS_SUCCESS,
    "completed": STATUS_SUCCESS,
    "max_rounds": "max_rounds",
    "interrupted": STATUS_ERROR,
    "llm_error": STATUS_ERROR,
}


class Ci2labAdapter:
    """Run a task with the local ci2lab harness, in-process."""

    def __init__(self, *, multi: bool = False) -> None:
        """Initialize the adapter.

        Args:
            multi: When true, use the multi-agent orchestrator
                (``run_multi_agent``); otherwise the single ReAct agent.
        """
        self.multi = multi
        self.name = "ci2lab-multi" if multi else "ci2lab"

    def run(
        self,
        task: BenchTask,
        workspace: Path,
        *,
        model: str,
        runs_dir: Path,
        timeout: int,
    ) -> RunResult:
        """Run one sample of ``task`` and return its metrics."""
        from ci2lab.harness import AgentConfig, default_selection, run_agent
        from ci2lab.harness.llm_errors import LLMError

        write_enabled = task.write_tools_enabled if task.write_tools_enabled is not None else True
        config = AgentConfig(
            cwd=str(workspace),
            max_rounds=task.max_rounds,
            stream=False,
            auto_confirm=True,
            run_log_enabled=True,
            runs_dir=str(runs_dir),
            write_tools_enabled=write_enabled,
            require_diff_preview=False,
            confirm_callback=lambda _name, _src: True,
            suppress_run_saved_message=True,
            security_engine="ci2lab",
        )
        selection = default_selection(model)

        status = STATUS_SUCCESS
        error: str | None = None
        final = ""
        started = time.perf_counter()
        try:
            with patch("ci2lab.console.console.print"):
                if self.multi:
                    from ci2lab.harness.multiagent import run_multi_agent

                    final = run_multi_agent(task.prompt, selection, config=config)
                else:
                    final = run_agent(task.prompt, selection, config=config)
        except LLMError as exc:
            status = STATUS_ERROR
            error = exc.user_message
            final = exc.user_message
        wall = time.perf_counter() - started

        usage = config.token_usage.session
        prompt_tokens = usage.prompt_tokens if usage.available else None
        completion_tokens = usage.completion_tokens if usage.available else None
        total_tokens = usage.total_tokens if usage.available else None

        run_dir = _find_latest_run_dir(runs_dir)
        tool_calls: int | None = None
        rounds: int | None = None
        if run_dir is not None:
            tool_calls = _count_tool_calls(run_dir)
            rounds, run_status = _read_run_json(run_dir)
            if status == STATUS_SUCCESS and run_status:
                status = _RUN_STATUS_MAP.get(run_status, run_status)

        return RunResult(
            final_answer=final or "",
            status=status,
            wall_clock_s=wall,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            rounds=rounds,
            tool_calls=tool_calls,
            error=error,
            transcript_path=str(run_dir) if run_dir is not None else None,
            raw={"model": usage.model or model},
        )


def _find_latest_run_dir(runs_parent: Path) -> Path | None:
    """Return the most recently modified subdirectory of ``runs_parent``."""
    if not runs_parent.is_dir():
        return None
    dirs = [p for p in runs_parent.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def _read_run_json(run_dir: Path) -> tuple[int | None, str | None]:
    """Read ``run.json`` defensively, returning ``(rounds, status)``."""
    path = run_dir / "run.json"
    if not path.is_file():
        return None, None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    rounds = data.get("rounds")
    if rounds is None:
        rounds = data.get("rounds_completed")
    if rounds is None:
        phases = data.get("phases")
        if isinstance(phases, list):
            phase_rounds = [
                int(phase["rounds"])
                for phase in phases
                if isinstance(phase, dict) and isinstance(phase.get("rounds"), int)
            ]
            rounds = sum(phase_rounds) if phase_rounds else None
    status = data.get("status") or data.get("final_status")
    if status is None:
        decision = data.get("orchestration_decision_final")
        if isinstance(decision, dict):
            status = decision.get("final_status")
    return (int(rounds) if isinstance(rounds, int) else None), (
        str(status) if status is not None else None
    )


def _count_tool_calls(run_dir: Path) -> int | None:
    """Count tool calls in either single-agent or multi-agent run artifacts."""
    direct = run_dir / "tool_calls.jsonl"
    if direct.is_file():
        direct_count = len(load_tool_calls_jsonl(direct))
        if direct_count:
            return direct_count
    trace = run_dir / "multiagent_trace.json"
    if trace.is_file():
        try:
            data = json.loads(trace.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        phases = data.get("phases")
        if isinstance(phases, list):
            return sum(
                len(phase.get("tool_calls") or []) for phase in phases if isinstance(phase, dict)
            )
    return len(load_tool_calls_jsonl(direct)) if direct.is_file() else None
