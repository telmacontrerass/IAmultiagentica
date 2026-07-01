"""Adapter for the Claude Code CLI (H1 only, under a Claude subscription).

Runs ``claude -p "<prompt>" --output-format json`` headlessly in the workspace
and parses the result JSON for the final answer, token usage and the
``total_cost_usd`` Claude Code reports (a computed equivalent under a
subscription, not an invoice).

Environment knobs (so any Claude Code version can be driven without a code
change): ``BENCH_CLAUDE_CMD`` supplies a full command template (placeholders
``{prompt}``/``{model}``/``{workspace}``; prompt piped to stdin when the template
omits ``{prompt}``), ``BENCH_CLAUDE_BIN`` overrides the ``claude`` executable, and
``BENCH_CLAUDE_ARGS`` injects extra CLI args before the prompt. The exact command
is written to ``claude_cmd.txt`` in the run directory for debugging; confirm the
result JSON field names against the installed CLI during the Day-4 auth spike
(see ``docs/BENCHMARKING.md`` §6).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

from ci2lab.bench.adapters.base import render_command_template
from ci2lab.bench.metrics import STATUS_ERROR, STATUS_SUCCESS, STATUS_TIMEOUT, RunResult
from ci2lab.bench.task import BenchTask

__all__ = ["ClaudeCodeAdapter"]


class ClaudeCodeAdapter:
    """Subprocess adapter for Claude Code in non-interactive (`-p`) mode."""

    name = "claude-code"

    def __init__(self) -> None:
        """Read the Claude Code env knobs (command template, binary, extra args)."""
        self.template = os.environ.get("BENCH_CLAUDE_CMD", "").strip()
        self.binary = os.environ.get("BENCH_CLAUDE_BIN", "claude")
        self.extra_args = shlex.split(os.environ.get("BENCH_CLAUDE_ARGS", ""))

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
        if self.template:
            cmd, stdin_text = render_command_template(
                self.template, prompt=task.prompt, model=model, workspace=workspace
            )
        else:
            cmd = [
                self.binary,
                "-p",
                task.prompt,
                "--output-format",
                "json",
                "--dangerously-skip-permissions",
            ]
            if model:
                cmd += ["--model", model]
            cmd += self.extra_args
            stdin_text = None

        runs_dir.mkdir(parents=True, exist_ok=True)
        rendered = " ".join(shlex.quote(part) for part in cmd)
        if stdin_text is not None:
            rendered += "   # (prompt piped to stdin)"
        (runs_dir / "claude_cmd.txt").write_text(rendered, encoding="utf-8")

        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return RunResult(
                "",
                STATUS_ERROR,
                time.perf_counter() - started,
                error=f"claude CLI not found (binary: {self.binary})",
            )
        except subprocess.TimeoutExpired:
            return RunResult("", STATUS_TIMEOUT, float(timeout), error="claude timed out")
        wall = time.perf_counter() - started
        if proc.stderr:
            (runs_dir / "claude_stderr.txt").write_text(proc.stderr, encoding="utf-8")

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
