"""Glue for running ci2lab as a Terminal-Bench (Harbor) installed agent.

Terminal-Bench 2.x runs on the *Harbor* harness. A custom agent that is an
installed CLI subclasses ``harbor.agents.installed.base.BaseInstalledAgent``,
installs itself into each task's container, and drives itself over the
container's shell. That thin ``harbor``-importing subclass lives outside this
package (``benchmarks/harbor/ci2lab_harbor.py``) so the heavy Harbor dependency
never enters ci2lab's own dependency set; the *logic* it needs — building the
headless run command, wiring ci2lab at a local model, and reading token usage
back out of ci2lab's run log — lives here, where the quality gates and test
suite cover it.

Harbor reports zero tokens for installed agents, so the benchmark's token
numbers come from ci2lab's own ``run_summary.json`` (read via
:func:`read_run_summary`), not from Harbor.

See [`benchmarks/harbor/README.md`](../../benchmarks/harbor/README.md) for how
to run a suite and [`docs/BENCHMARKING.md`](../../docs/BENCHMARKING.md) for the
methodology.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CONTAINER_LOG_PATH",
    "CONTAINER_RUNS_DIR",
    "CONTAINER_WORKDIR",
    "DEFAULT_BACKEND_URL",
    "DEFAULT_MODEL",
    "DEFAULT_NUM_CTX",
    "TokenReadback",
    "agent_env",
    "build_run_command",
    "find_latest_run_summary",
    "read_run_summary",
]

DEFAULT_MODEL = "qwen3-coder:30b"
"""Default benchmark model M: Qwen3-Coder-30B-A3B — native tool calling, fits an A6000."""

DEFAULT_BACKEND_URL = "http://host.docker.internal:11434/v1"
"""Ollama OpenAI-compatible endpoint reachable from inside a task container."""

DEFAULT_NUM_CTX = 32768
"""Context window to request; the model supports far more, capped for KV headroom."""

CONTAINER_WORKDIR = "/app"
"""Default working directory inside a Terminal-Bench task container.

Most terminal-bench tasks operate in ``/app``; confirm per dataset and override
via the ``workdir`` agent kwarg if a task uses a different root.
"""

CONTAINER_RUNS_DIR = "/logs/agent/ci2lab-runs"
"""Where ci2lab writes its run log inside the container.

``/logs/agent`` is Harbor's per-agent log mount (the same path the built-in
opencode agent tees to), so the run log — and thus the token counts — survives
back to the host ``logs_dir`` for :func:`read_run_summary`.
"""

CONTAINER_LOG_PATH = "/logs/agent/ci2lab.txt"
"""Where the agent's combined stdout/stderr is teed for audit."""


@dataclass
class TokenReadback:
    """Token usage and status read back from a ci2lab ``run_summary.json``."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    rounds: int | None
    status: str | None


def agent_env(
    *,
    model: str = DEFAULT_MODEL,
    backend_url: str = DEFAULT_BACKEND_URL,
    num_ctx: int = DEFAULT_NUM_CTX,
) -> dict[str, str]:
    """Build the environment that points ci2lab at a local model, non-interactively.

    ci2lab supplies its own model client, so Terminal-Bench's model routing is
    bypassed entirely: these variables make ci2lab talk to the host's Ollama
    OpenAI-compatible endpoint with no API key and no cloud egress.

    Args:
        model: Ollama model tag to run (the benchmark's fixed model M).
        backend_url: OpenAI-compatible base URL reachable from the container.
        num_ctx: Context window to request (drives Ollama's ``num_ctx``).

    Returns:
        Environment variables to inject into the agent's container commands.
    """
    return {
        "CI2LAB_MODEL": model,
        "CI2LAB_BACKEND_URL": backend_url,
        "CI2LAB_NUM_CTX": str(num_ctx),
        # Mirror the shipped product configuration used by the internal bench
        # adapter (diff-preview gate off) so both benchmark surfaces measure the
        # same harness rather than a weaker variant.
        "CI2LAB_REQUIRE_DIFF_PREVIEW": "0",
    }


def build_run_command(
    instruction: str,
    *,
    multi: bool = False,
    workdir: str = CONTAINER_WORKDIR,
    security_engine: str = "ci2lab",
    runs_dir: str = CONTAINER_RUNS_DIR,
    log_path: str = CONTAINER_LOG_PATH,
) -> str:
    """Build the shell command that runs one ci2lab task headlessly in a container.

    Terminal-Bench grades the container's final state, not the agent's stdout, so
    the command's job is to make ci2lab's edits land in ``workdir`` and to leave a
    parseable run log under ``runs_dir``. Output is teed to ``log_path`` for audit.
    The ``--multi-agent`` orchestrator flag is a *global* flag and must precede the
    ``agent`` subcommand; every interpolated value is ``shlex``-quoted so an
    adversarial task prompt cannot break out of its argument.

    Args:
        instruction: The task prompt handed to ci2lab verbatim.
        multi: Use the multi-agent orchestrator (the H3 control) when true.
        workdir: Container directory ci2lab operates in (the graded files).
        security_engine: ci2lab security engine; ``ci2lab`` mirrors the internal
            benchmark adapter's product configuration.
        runs_dir: Directory for ci2lab's run log (token usage, status).
        log_path: File the combined stdout/stderr is teed to.

    Returns:
        A single shell command string suitable for Harbor's ``exec_as_agent``.
    """
    global_flags = "--multi-agent " if multi else ""
    return (
        f"ci2lab {global_flags}agent --yes --no-stream "
        f"--security-engine {shlex.quote(security_engine)} "
        f"--workspace {shlex.quote(workdir)} "
        f"--runs-dir {shlex.quote(runs_dir)} "
        f"{shlex.quote(instruction)} "
        f"2>&1 | tee {shlex.quote(log_path)}"
    )


def find_latest_run_summary(logs_dir: Path) -> Path | None:
    """Return the most recently modified ``run_summary.json`` under ``logs_dir``.

    Args:
        logs_dir: Directory to search recursively (Harbor's host log mount).

    Returns:
        The newest ``run_summary.json`` path, or ``None`` when none exists.
    """
    if not logs_dir.is_dir():
        return None
    summaries = list(logs_dir.rglob("run_summary.json"))
    if not summaries:
        return None
    return max(summaries, key=lambda p: p.stat().st_mtime)


def read_run_summary(logs_dir: Path) -> TokenReadback | None:
    """Read ci2lab's token usage and status back from its latest run log.

    Terminal-Bench reports zero tokens for installed agents, so the benchmark's
    token numbers must come from ci2lab's own run log, which the agent writes into
    the container path mounted at ``logs_dir`` on the host.

    Args:
        logs_dir: The host directory Harbor mounted as the agent's log dir.

    Returns:
        The parsed usage, or ``None`` when no run log is present or readable.
    """
    path = find_latest_run_summary(logs_dir)
    if path is None:
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    usage = data.get("token_usage")
    usage = usage if isinstance(usage, dict) else {}
    rounds = data.get("rounds")
    status = data.get("status")
    return TokenReadback(
        prompt_tokens=_as_int(usage.get("prompt_tokens")),
        completion_tokens=_as_int(usage.get("completion_tokens")),
        total_tokens=_as_int(usage.get("total_tokens")),
        rounds=rounds if isinstance(rounds, int) else None,
        status=str(status) if status is not None else None,
    )


def _as_int(value: Any) -> int:
    """Coerce a JSON value to ``int``, defaulting to ``0`` for anything else."""
    return value if isinstance(value, int) else 0
