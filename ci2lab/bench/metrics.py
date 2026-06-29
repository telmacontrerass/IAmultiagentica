"""Run results, the token→USD cost model, and aggregation statistics.

A :class:`RunResult` is the normalized output of any agent adapter for a single
(task, agent, sample). Cost is always *derived from measured tokens* via a price
table (see ``docs/BENCHMARKING.md`` §4.2) — for local/open models the USD figure
is an imputed hosted-rate number, never an invoice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "RunResult",
    "compute_cost_usd",
    "load_prices",
    "mean",
    "median",
    "pass_at_k",
]

# Run status values recorded by adapters.
STATUS_SUCCESS = "success"
STATUS_MAX_ROUNDS = "max_rounds"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"


@dataclass
class RunResult:
    """Normalized result of one agent run on one task sample."""

    final_answer: str
    status: str
    wall_clock_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    rounds: int | None = None
    tool_calls: int | None = None
    error: str | None = None
    transcript_path: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this result to a JSON-friendly mapping."""
        return {
            "final_answer": self.final_answer,
            "status": self.status,
            "wall_clock_s": round(self.wall_clock_s, 3),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "rounds": self.rounds,
            "tool_calls": self.tool_calls,
            "error": self.error,
            "transcript_path": self.transcript_path,
        }


def load_prices(path: Path | None = None) -> dict[str, Any]:
    """Load the per-million-token price table.

    Args:
        path: Path to ``prices.json``; defaults to ``benchmarks/prices.json``
            resolved from the repo root.

    Returns:
        The parsed price table, or an empty mapping when the file is missing.
    """
    if path is None:
        from ci2lab.bench.task import default_results_dir

        path = default_results_dir().parent / "prices.json"
    if not path.is_file():
        return {}
    parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return parsed


def compute_cost_usd(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    model: str,
    prices: dict[str, Any],
) -> float | None:
    """Derive an (imputed) USD cost from token counts and a price table.

    Args:
        prompt_tokens: Input tokens for the run, or ``None``.
        completion_tokens: Output tokens for the run, or ``None``.
        model: Model identifier used to look up per-token prices.
        prices: A price table as produced by :func:`load_prices`.

    Returns:
        ``input_tokens * input_price + output_tokens * output_price`` in USD
        (rounded to 6 dp), or ``None`` when no tokens or no applicable price are
        available.
    """
    if prompt_tokens is None and completion_tokens is None:
        return None
    entry = (prices.get("models") or {}).get(model) or prices.get("default")
    if not isinstance(entry, dict):
        return None
    in_price = float(entry.get("input_per_mtok", 0.0))
    out_price = float(entry.get("output_per_mtok", 0.0))
    cost = (prompt_tokens or 0) / 1_000_000 * in_price
    cost += (completion_tokens or 0) / 1_000_000 * out_price
    return round(cost, 6)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased Pass@k estimator (Chen et al., HumanEval).

    Estimates the probability that at least one of ``k`` samples drawn from
    ``n`` total is correct, given ``c`` correct samples.

    Args:
        n: Total number of samples for the (task, agent).
        c: Number of correct (solved) samples.
        k: The ``k`` in Pass@k.

    Returns:
        The estimated Pass@k in ``[0.0, 1.0]``.
    """
    if n <= 0 or k <= 0:
        return 0.0
    if c <= 0:
        return 0.0
    k = min(k, n)
    if n - c < k:
        return 1.0
    prob_none = 1.0
    for i in range(k):
        prob_none *= (n - c - i) / (n - i)
    return 1.0 - prob_none


def mean(values: list[float]) -> float | None:
    """Return the arithmetic mean, or ``None`` for an empty list."""
    if not values:
        return None
    return sum(values) / len(values)


def median(values: list[float]) -> float | None:
    """Return the median, or ``None`` for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
