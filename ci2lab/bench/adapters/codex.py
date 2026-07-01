"""Adapter for the OpenAI Codex CLI.

Runs ``codex exec --json "<prompt>"`` in the workspace and parses the JSONL
event stream for the final message and token usage. In H1 Codex runs under a
ChatGPT subscription with its default model; in H2 it runs the shared open model
M locally.

Environment knobs (so any Codex version can be driven without a code change):

- ``BENCH_CODEX_OSS=1`` — add ``--oss`` to the ``exec`` subcommand, routing Codex
  at a local model (the H2 arm). Note: ``--oss`` is placed *after* ``exec`` —
  placing it before the subcommand does not take effect and Codex falls back to
  the ChatGPT account (which rejects non-OpenAI models).
- ``BENCH_CODEX_LOCAL_PROVIDER`` — the local provider for ``--oss`` (default
  ``ollama``; Codex also supports ``lmstudio``). Set to empty to omit the flag on
  Codex versions that default the provider themselves.
- ``BENCH_CODEX_ARGS`` — extra CLI args inserted before the prompt, e.g.
  ``-c model_provider=oss`` or a custom base URL. Use this if your Codex version
  selects the local provider differently.
- ``BENCH_CODEX_BIN`` — override the ``codex`` executable path.

Codex's JSONL schema is version-specific, so parsing is intentionally defensive
(it scans for known fields). The exact command is written to ``codex_cmd.txt`` and
the raw stream to ``codex_events.jsonl`` in the run directory for debugging.
"""

from __future__ import annotations

import json
import os
import shlex
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
        """Read the Codex env knobs (OSS mode, local provider, extra args, binary)."""
        self.oss = _env_flag("BENCH_CODEX_OSS")
        self.local_provider = os.environ.get("BENCH_CODEX_LOCAL_PROVIDER", "ollama")
        self.binary = os.environ.get("BENCH_CODEX_BIN", "codex")
        self.extra_args = shlex.split(os.environ.get("BENCH_CODEX_ARGS", ""))

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
        cmd = _build_command(
            task.prompt,
            model=model,
            oss=self.oss,
            local_provider=self.local_provider,
            extra_args=self.extra_args,
            binary=self.binary,
            workspace=workspace,
        )
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "codex_cmd.txt").write_text(
            " ".join(shlex.quote(part) for part in cmd), encoding="utf-8"
        )

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
                "",
                STATUS_ERROR,
                time.perf_counter() - started,
                error=f"codex CLI not found (binary: {self.binary})",
            )
        except subprocess.TimeoutExpired:
            return RunResult("", STATUS_TIMEOUT, float(timeout), error="codex timed out")
        wall = time.perf_counter() - started

        (runs_dir / "codex_events.jsonl").write_text(proc.stdout, encoding="utf-8")
        if proc.stderr:
            (runs_dir / "codex_stderr.txt").write_text(proc.stderr, encoding="utf-8")

        events = _parse_jsonl(proc.stdout)
        backend_error = _find_error(events) or _find_error_text(proc.stdout)
        final = _find_final_text(events)
        prompt_tokens, completion_tokens = _find_tokens(events)
        total = None
        if prompt_tokens is not None and completion_tokens is not None:
            total = prompt_tokens + completion_tokens

        failed = proc.returncode != 0 or backend_error is not None
        raw: dict[str, Any] = {
            "returncode": proc.returncode,
            "event_count": len(events),
            "cmd": cmd,
        }

        if failed and not final:
            message = backend_error or (proc.stderr or proc.stdout or "codex failed").strip()
            return RunResult(
                final_answer=(backend_error or proc.stdout or "")[:2000],
                status=STATUS_ERROR,
                wall_clock_s=wall,
                error=message[:500],
                transcript_path=str(runs_dir / "codex_events.jsonl"),
                raw=raw,
            )

        return RunResult(
            final_answer=final,
            status=STATUS_ERROR if failed else STATUS_SUCCESS,
            wall_clock_s=wall,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            error=backend_error,
            transcript_path=str(runs_dir / "codex_events.jsonl"),
            raw=raw,
        )


def _build_command(
    prompt: str,
    *,
    model: str,
    oss: bool,
    local_provider: str = "",
    extra_args: list[str],
    binary: str,
    workspace: Path,
) -> list[str]:
    """Assemble the ``codex exec`` argv.

    ``--oss`` (when requested) is attached to the ``exec`` subcommand — its
    placement is the fix for the ChatGPT-account fallback — and is followed by
    ``--local-provider <name>`` so Codex knows which local backend to use. The
    prompt is the final positional argument.

    Args:
        prompt: The task prompt (positional argument, placed last).
        model: Model tag to pin with ``--model`` (omitted when empty).
        oss: Whether to add ``--oss`` to route at a local model.
        local_provider: Local provider name for ``--oss`` (e.g. ``ollama``);
            omitted when empty or when ``oss`` is false.
        extra_args: Extra CLI args from ``BENCH_CODEX_ARGS`` (an escape hatch).
        binary: The ``codex`` executable name/path.
        workspace: Working directory passed via ``--cd``.

    Returns:
        The full argument vector for :func:`subprocess.run`.
    """
    cmd = [binary, "exec", "--json"]
    if oss:
        cmd.append("--oss")
        if local_provider:
            cmd += ["--local-provider", local_provider]
    if model:
        cmd += ["--model", model]
    cmd += extra_args
    cmd += ["--cd", str(workspace)]
    cmd.append(prompt)
    return cmd


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


def _find_error(events: list[dict[str, Any]]) -> str | None:
    """Return a backend error message from an error-shaped event, if any.

    Only ``detail`` and ``error`` are treated as error signals (``message`` is
    reused for normal assistant text, so it is excluded here).
    """
    for event in events:
        detail = event.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        err = event.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()
        if isinstance(err, dict):
            msg = err.get("message") or err.get("detail")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
    return None


def _find_error_text(text: str) -> str | None:
    """Parse ``text`` as a single JSON object and extract an error, if present."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict):
        return _find_error([obj])
    return None


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
