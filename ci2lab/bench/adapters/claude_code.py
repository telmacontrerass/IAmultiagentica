"""Adapter for the Claude Code CLI (H1 only, under a Claude subscription).

Runs ``claude -p "<prompt>" --output-format json`` headlessly in the workspace
and parses the result JSON for the final answer, token usage and the
``total_cost_usd`` Claude Code reports (a computed equivalent under a
subscription, not an invoice). The exact field names should be confirmed against
the installed CLI during the Day-4 auth spike (see ``docs/BENCHMARKING.md`` §6).
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from ci2lab.bench.metrics import STATUS_ERROR, STATUS_SUCCESS, STATUS_TIMEOUT, RunResult
from ci2lab.bench.task import BenchTask

__all__ = ["ClaudeCodeAdapter"]


class ClaudeCodeAdapter:
    """Subprocess adapter for Claude Code in non-interactive (`-p`) mode."""

    name = "claude-code"

    def run(
        self,
        task: BenchTask,
        workspace: Path,
        *,
        model: str,
        runs_dir: Path,
        timeout: int,
    ) -> RunResult:
        """Run one sample via the ``claude`` CLI and parse its JSON result."""
        cmd = [
            "claude",
            "-p",
            task.prompt,
            "--output-format",
            "json",
            "--permission-mode",
            "acceptEdits",
        ]
        if model:
            cmd += ["--model", model]

        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return RunResult(
                "", STATUS_ERROR, time.perf_counter() - started, error="claude CLI not found"
            )
        except subprocess.TimeoutExpired:
            return RunResult("", STATUS_TIMEOUT, float(timeout), error="claude timed out")
        wall = time.perf_counter() - started

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return RunResult(
                proc.stdout,
                STATUS_ERROR,
                wall,
                error="unparseable claude output: " + (proc.stderr or "")[:300],
            )
        if not isinstance(data, dict):
            return RunResult(str(data), STATUS_ERROR, wall, error="unexpected claude output shape")

        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "claude_result.json").write_text(proc.stdout, encoding="utf-8")

        final = str(data.get("result") or data.get("text") or "")
        usage = data.get("usage") or {}
        prompt_tokens = _maybe_int(usage.get("input_tokens"))
        completion_tokens = _maybe_int(usage.get("output_tokens"))
        total = None
        if prompt_tokens is not None and completion_tokens is not None:
            total = prompt_tokens + completion_tokens
        status = STATUS_ERROR if data.get("is_error") else STATUS_SUCCESS
        return RunResult(
            final_answer=final,
            status=status,
            wall_clock_s=wall,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            cost_usd=_maybe_float(data.get("total_cost_usd")),
            rounds=_maybe_int(data.get("num_turns")),
            transcript_path=str(runs_dir / "claude_result.json"),
            raw=data,
        )


def _maybe_int(value: object) -> int | None:
    """Coerce ``value`` to ``int`` when possible, else ``None``."""
    return value if isinstance(value, int) else None


def _maybe_float(value: object) -> float | None:
    """Coerce a numeric ``value`` to ``float`` when possible, else ``None``."""
    if isinstance(value, (int, float)):
        return float(value)
    return None
