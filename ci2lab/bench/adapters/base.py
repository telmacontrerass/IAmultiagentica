"""The :class:`AgentAdapter` protocol and adapter registry."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ci2lab.bench.metrics import RunResult
from ci2lab.bench.task import BenchTask

__all__ = ["ADAPTER_NAMES", "AgentAdapter", "get_adapter"]

ADAPTER_NAMES = ("ci2lab", "ci2lab-multi", "claude-code", "codex")
"""All registered adapter (condition) names."""


class AgentAdapter(Protocol):
    """One agent under test. Runs a single task sample and reports metrics."""

    name: str

    def run(
        self,
        task: BenchTask,
        workspace: Path,
        *,
        model: str,
        runs_dir: Path,
        timeout: int,
    ) -> RunResult:
        """Run ``task`` in ``workspace`` and return a normalized result.

        Args:
            task: The task to run (its prompt is the input verbatim).
            workspace: The directory the agent operates in.
            model: Model identifier (Ollama tag, or empty for a CLI's default).
            runs_dir: Directory for this run's transcript / log artifacts.
            timeout: Hard per-run wall-clock cap in seconds.

        Returns:
            A :class:`~ci2lab.bench.metrics.RunResult`; ``solved`` is decided
            later by the verifier, not the adapter.
        """
        ...


def get_adapter(name: str) -> AgentAdapter:
    """Resolve an adapter name to a concrete adapter instance.

    Args:
        name: One of :data:`ADAPTER_NAMES`.

    Returns:
        The matching adapter.

    Raises:
        ValueError: If ``name`` is not a known adapter.
    """
    if name in ("ci2lab", "ci2lab-multi"):
        from ci2lab.bench.adapters.ci2lab_adapter import Ci2labAdapter

        return Ci2labAdapter(multi=name == "ci2lab-multi")
    if name == "claude-code":
        from ci2lab.bench.adapters.claude_code import ClaudeCodeAdapter

        return ClaudeCodeAdapter()
    if name == "codex":
        from ci2lab.bench.adapters.codex import CodexAdapter

        return CodexAdapter()
    raise ValueError(f"Unknown agent {name!r}; expected one of {list(ADAPTER_NAMES)}")
