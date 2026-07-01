"""Tests for the benchmark report aggregation and validity warnings."""

from __future__ import annotations

import json
from typing import Any

from ci2lab.bench.report import (
    aggregate_by_agent,
    aggregate_by_task_agent,
    load_records,
    validity_warnings,
)


def _row(
    agent: str,
    task: str,
    solved: bool,
    *,
    status: str = "success",
    total_tokens: int | None = 1000,
    false_positive: bool = False,
    wall: float = 1.0,
    cost: float = 0.001,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "task_id": task,
        "solved": solved,
        "status": status,
        "total_tokens": total_tokens,
        "false_positive": false_positive,
        "wall_clock_s": wall,
        "cost_usd": cost,
    }


def test_aggregate_by_task_agent_pass_rates() -> None:
    rows = [
        _row("a", "t1", True),
        _row("a", "t1", False),
        _row("a", "t1", True),
        _row("a", "t1", False),
        _row("a", "t1", True),
    ]
    out = aggregate_by_task_agent(rows)
    assert len(out) == 1
    row = out[0]
    assert row["n"] == 5
    assert row["solved"] == 3
    assert row["pass_at_1"] == 0.6
    assert row["pass_at_k"] == 1.0  # n - c = 2 < 5


def test_aggregate_by_agent_macro_average() -> None:
    rows = [_row("a", "t1", True), _row("a", "t2", False)]
    out = aggregate_by_agent(rows)
    assert len(out) == 1
    assert out[0]["macro_pass_at_1"] == 0.5  # (1.0 + 0.0) / 2
    assert out[0]["runs"] == 2


def test_validity_flags_error_status() -> None:
    warnings = validity_warnings([_row("codex", "t1", False, status="error", total_tokens=None)])
    assert any("errored" in w for w in warnings)


def test_validity_flags_false_positive() -> None:
    warnings = validity_warnings([_row("codex", "t1", False, false_positive=True)])
    assert any("false_positive" in w for w in warnings)


def test_validity_flags_null_tokens_on_success() -> None:
    warnings = validity_warnings([_row("codex", "t1", False, status="success", total_tokens=None)])
    assert any("no token count" in w for w in warnings)


def test_validity_flags_uniform_tokens() -> None:
    rows = [
        _row("codex", "t1", False, total_tokens=6500),
        _row("codex", "t2", False, total_tokens=6510),
        _row("codex", "t3", False, total_tokens=6490),
    ]
    warnings = validity_warnings(rows)
    assert any("near-uniform" in w for w in warnings)


def test_validity_clean_when_varied() -> None:
    rows = [
        _row("ci2lab", "t1", True, total_tokens=10000),
        _row("ci2lab", "t2", True, total_tokens=40000),
        _row("ci2lab", "t3", True, total_tokens=25000),
    ]
    assert validity_warnings(rows) == []


def test_load_records_from_dir(tmp_path) -> None:
    run = tmp_path / "run1"
    run.mkdir()
    (run / "results.jsonl").write_text(
        json.dumps(_row("a", "t1", True)) + "\n" + json.dumps(_row("a", "t1", False)) + "\n",
        encoding="utf-8",
    )
    rows = load_records([tmp_path])
    assert len(rows) == 2
    assert rows[0]["agent"] == "a"
