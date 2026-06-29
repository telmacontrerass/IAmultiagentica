"""ci2lab benchmark suite: cross-agent performance harness.

This package measures how the ci2lab harness performs against OpenAI Codex CLI
and Claude Code. It is deliberately separate from the test/eval suite: tests
check the harness *works*; benchmarks quantify how *well* it performs, run live,
and never gate CI.

See [`docs/BENCHMARKING.md`](../../docs/BENCHMARKING.md) for the methodology and
[`benchmarks/`](../../benchmarks/) for the task definitions and results.
"""

from __future__ import annotations

from ci2lab.bench.metrics import RunResult, compute_cost_usd, pass_at_k
from ci2lab.bench.task import BenchTask, VerifierSpec, load_tasks

__all__ = [
    "BenchTask",
    "RunResult",
    "VerifierSpec",
    "compute_cost_usd",
    "load_tasks",
    "pass_at_k",
]
