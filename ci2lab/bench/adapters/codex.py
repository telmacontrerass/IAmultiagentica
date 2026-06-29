"""Adapter for the OpenAI Codex CLI.

Runs ``codex exec --json "<prompt>"`` in the workspace and parses the JSONL
event stream for the final message and token usage. In H1 Codex runs under a
ChatGPT subscription with its default model; in H2 it runs the shared open model
M via ``--oss`` (enable by setting ``BENCH_CODEX_OSS=1``).

Codex's JSONL schema is version-specific, so parsing here is intentionally
defensive (it scans for known fields) and should be confirmed against the
installed CLI during the Day-4 spike (see ``docs/BENCHMARKING.md`` §6).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from ci2lab.bench.metrics import STATUS_ERROR, STATUS_SUCCESS, STATUS_TIMEOUT, RunResult
from ci2lab.bench.task import BenchTask

__all__ = ["CodexAdapter"]


class CodexAdapter:
    """Subprocess adapter for ``codex exec`` in non-interactive JSON mode."""

    name = "codex"

    def __init__(self) -> None:
        """Read the ``BENCH_CODEX_OSS`` flag that routes Codex at a local model."""
        self.oss = _env_flag("BENCH_CODEX_OSS")

    def run(
        self,
        task: BenchTask,
        workspace: Path,
        *,
        model: str,
        runs_dir: Path,
        timeout: int,
    ) -> RunResult:
        """Run one sample via the ``codex`` CLI and parse its JSONL events."""
        cmd = ["codex"]
        if self.oss:
            cmd.append("--oss")
        cmd += ["exec", "--json"]
        if model:
            cmd += ["--model", model]
        cmd += ["--cd", str(workspace), task.prompt]

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
                "", STATUS_ERROR, time.perf_counter() - started, error="codex CLI not found"
            )
        except subprocess.TimeoutExpired:
            return RunResult("", STATUS_TIMEOUT, float(timeout), error="codex timed out")
        wall = time.perf_counter() - started

        events = _parse_jsonl(proc.stdout)
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "codex_events.jsonl").write_text(proc.stdout, encoding="utf-8")

        final = _find_final_text(events)
        prompt_tokens, completion_tokens = _find_tokens(events)
        total = None
        if prompt_tokens is not None and completion_tokens is not None:
            total = prompt_tokens + completion_tokens
        if not events and proc.returncode != 0:
            return RunResult(
                proc.stdout, STATUS_ERROR, wall, error=(proc.stderr or "codex failed")[:300]
            )

        return RunResult(
            final_answer=final,
            status=STATUS_SUCCESS if proc.returncode == 0 else STATUS_ERROR,
            wall_clock_s=wall,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            transcript_path=str(runs_dir / "codex_events.jsonl"),
            raw={"event_count": len(events)},
        )


def _env_flag(name: str) -> bool:
    """Whether environment variable ``name`` is set to a truthy value."""
    return os.environ.get(name, "").strip().lower() not in ("", "0", "false", "no")


def _parse_jsonl(text: str) -> list[dict[str, Any]]:
    """Parse a JSONL string into a list of objects, skipping bad lines."""
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def _find_final_text(events: list[dict[str, Any]]) -> str:
    """Return the last non-empty assistant/message text across events."""
    text = ""
    for event in events:
        for key in ("text", "message", "content", "last_agent_message", "agent_message"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                text = value
    return text


def _find_tokens(events: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """Scan events for the most recent input/output token counts."""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    for event in events:
        found = _scan_tokens(event)
        if found[0] is not None:
            prompt_tokens = found[0]
        if found[1] is not None:
            completion_tokens = found[1]
    return prompt_tokens, completion_tokens


def _scan_tokens(obj: Any) -> tuple[int | None, int | None]:
    """Recursively find ``input_tokens``/``output_tokens`` in a nested object."""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("input_tokens", "prompt_tokens") and isinstance(value, int):
                prompt_tokens = value
            elif key in ("output_tokens", "completion_tokens") and isinstance(value, int):
                completion_tokens = value
            else:
                nested = _scan_tokens(value)
                prompt_tokens = nested[0] if nested[0] is not None else prompt_tokens
                completion_tokens = nested[1] if nested[1] is not None else completion_tokens
    return prompt_tokens, completion_tokens
