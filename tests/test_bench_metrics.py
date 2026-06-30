"""Tests for the benchmark metrics: Pass@k, token->USD cost, and aggregation."""

from __future__ import annotations

from ci2lab.bench.metrics import (
    RunResult,
    compute_cost_usd,
    load_prices,
    mean,
    median,
    pass_at_k,
)
from ci2lab.bench.runner import _evidence_metrics
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
