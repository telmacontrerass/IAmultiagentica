"""Tests for the benchmark metrics: Pass@k, token->USD cost, and aggregation."""

from __future__ import annotations

from typing import Any

from ci2lab.bench.metrics import (
    RunResult,
    bootstrap_ci,
    compute_cost_usd,
    format_optional_number,
    is_number,
    load_prices,
    mean,
    median,
    optional_round,
    pass_at_k,
)
from ci2lab.bench.runner import _aggregate, _evidence_metrics
from ci2lab.bench.task import BenchTask


def test_pass_at_k_extremes() -> None:
    assert pass_at_k(5, 5, 1) == 1.0
    assert pass_at_k(5, 0, 1) == 0.0
    assert pass_at_k(0, 0, 1) == 0.0
    assert pass_at_k(5, 1, 0) == 0.0


def test_pass_at_1_is_fraction() -> None:
    assert pass_at_k(4, 2, 1) == 0.5


def test_pass_at_k_known_values() -> None:
    # n=5, c=1, k=5: n-c < k -> guaranteed at least one correct.
    assert pass_at_k(5, 1, 5) == 1.0
    # n=5, c=1, k=2: 1 - (4/5)*(3/4) = 0.4
    assert abs(pass_at_k(5, 1, 2) - 0.4) < 1e-9


def test_pass_at_k_monotonic_in_k() -> None:
    assert pass_at_k(5, 1, 5) >= pass_at_k(5, 1, 1)


def test_compute_cost_usd_basic() -> None:
    prices = {"models": {"m": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}}
    assert compute_cost_usd(1_000_000, 1_000_000, "m", prices) == 3.0


def test_compute_cost_usd_none_tokens() -> None:
    prices = {"models": {"m": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}}
    assert compute_cost_usd(None, None, "m", prices) is None


def test_compute_cost_usd_unknown_model_no_default() -> None:
    assert compute_cost_usd(1000, 0, "unknown", {}) is None


def test_compute_cost_usd_falls_back_to_default() -> None:
    prices = {"default": {"input_per_mtok": 0.0, "output_per_mtok": 0.0}}
    assert compute_cost_usd(1000, 1000, "unknown", prices) == 0.0


def test_mean_and_median() -> None:
    assert mean([]) is None
    assert median([]) is None
    assert mean([1.0, 2.0, 3.0]) == 2.0
    assert median([1.0, 2.0, 3.0]) == 2.0
    assert median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_shared_numeric_formatters() -> None:
    assert is_number(1.5)
    assert not is_number(True)
    assert optional_round(1.234, 2) == 1.23
    assert optional_round(None, 2) is None
    assert format_optional_number(None) == "-"
    assert format_optional_number(1.25) == "1.25"


def test_bootstrap_ci_empty_is_none() -> None:
    assert bootstrap_ci([]) is None


def test_bootstrap_ci_single_observation_is_degenerate() -> None:
    # One observation → every resample is identical → a zero-width interval.
    assert bootstrap_ci([1.0]) == (1.0, 1.0)


def test_bootstrap_ci_constant_sample_has_zero_width() -> None:
    assert bootstrap_ci([0.0, 0.0, 0.0, 0.0]) == (0.0, 0.0)


def test_bootstrap_ci_is_deterministic() -> None:
    # Seeded RNG → identical bounds across calls, so reported CIs are replayable.
    values = [1.0, 1.0, 1.0, 0.0, 0.0]
    assert bootstrap_ci(values) == bootstrap_ci(values)


def test_bootstrap_ci_brackets_the_point_estimate() -> None:
    values = [1.0, 1.0, 1.0, 0.0, 0.0]  # mean = 0.6
    ci = bootstrap_ci(values)
    assert ci is not None
    low, high = ci
    assert 0.0 <= low <= 0.6 <= high <= 1.0


def test_bootstrap_ci_accepts_a_custom_statistic_and_confidence() -> None:
    ci = bootstrap_ci([2.0, 4.0, 6.0, 8.0, 10.0], statistic=median, confidence=0.8)
    assert ci is not None
    low, high = ci
    assert low <= high


def _agg_record(solved: bool) -> dict[str, Any]:
    """Minimal per-sample record with the keys ``_aggregate`` reads."""
    return {
        "task_id": "t1",
        "agent": "ci2lab",
        "solved": solved,
        "total_tokens": 100,
        "cost_usd": 0.001,
        "wall_clock_s": 1.0,
        "functional_success": solved,
        "evidence_success": None,
        "false_positive": False,
        "tool_violation_count": 0,
    }


def test_aggregate_attaches_bootstrap_cis_to_pass_rates() -> None:
    records = [_agg_record(True) for _ in range(3)] + [_agg_record(False) for _ in range(2)]
    rows = _aggregate(records)
    assert len(rows) == 1
    row = rows[0]

    assert row["pass_at_1"] == 0.6
    pass_1_ci = row["pass_at_1_ci"]
    assert isinstance(pass_1_ci, list) and len(pass_1_ci) == 2
    assert 0.0 <= pass_1_ci[0] <= 0.6 <= pass_1_ci[1] <= 1.0

    pass_k_ci = row["pass_at_k_ci"]
    assert isinstance(pass_k_ci, list) and len(pass_k_ci) == 2
    assert 0.0 <= pass_k_ci[0] <= pass_k_ci[1] <= 1.0


def test_load_real_prices_has_model_m() -> None:
    prices = load_prices()
    assert "qwen2.5-coder:32b" in (prices.get("models") or {})


def test_runresult_to_dict_roundtrip() -> None:
    result = RunResult(
        final_answer="ans",
        status="success",
        wall_clock_s=1.5,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )
    data = result.to_dict()
    assert data["status"] == "success"
    assert data["total_tokens"] == 15
    assert "raw" not in data


def test_evidence_metrics_from_multiagent_trace(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "multiagent_trace.json").write_text(
        """
{
  "failure_classification": {"failure_class": "scope_violation"},
  "phases": [
    {
      "role": "generalist_coder",
      "status": "completed",
      "tool_calls": [
        {"tool": "write_file", "ok": true},
        {"tool": "read_file", "ok": true},
        {"tool": "git_status", "ok": true}
      ]
    }
  ]
}
""",
        encoding="utf-8",
    )
    task = BenchTask.from_dict(
        {
            "id": "h3",
            "name": "H3",
            "category": "feat",
            "prompt": "p",
            "evidence_expectations": {
                "write_evidence_present": True,
                "readback_evidence_present": True,
                "scope_evidence_present": True,
            },
        }
    )
    result = RunResult(
        final_answer="completed",
        status="completed",
        wall_clock_s=1.0,
        transcript_path=str(run_dir),
    )

    metrics = _evidence_metrics(
        task,
        result=result,
        functional_success=True,
        changed_paths=["notes/out.txt"],
    )

    assert metrics["evidence_success"] is True
    assert metrics["false_positive"] is False
    assert metrics["write_evidence_present"] is True
    assert metrics["readback_evidence_present"] is True
    assert metrics["scope_evidence_present"] is True
    assert metrics["failure_classification"] == "scope_violation"
