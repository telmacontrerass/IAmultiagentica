"""Tests for the in-process ci2lab bench adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ci2lab.bench.adapters.ci2lab_adapter import Ci2labAdapter
from ci2lab.bench.task import BenchTask


def _task(**overrides: object) -> BenchTask:
    fields: dict[str, object] = {
        "id": "demo-01",
        "name": "demo",
        "category": "qa",
        "prompt": "Report the value. Do not modify any files.",
    }
    fields.update(overrides)
    return BenchTask(**fields)  # type: ignore[arg-type]


def test_adapter_measures_the_shipped_harness_configuration(tmp_path: Path) -> None:
    # The benchmark must run the same harness the product ships: completion
    # verification is on by default for real CLI/UI runs, so the adapter must
    # not silently benchmark a weaker variant with it stripped.
    captured: dict[str, object] = {}

    def fake_run_agent(prompt: str, selection: object, *, config: object = None) -> str:
        captured["config"] = config
        return "done"

    task = _task(write_tools_enabled=False, max_rounds=7)
    with patch("ci2lab.harness.run_agent", new=fake_run_agent):
        result = Ci2labAdapter().run(
            task,
            tmp_path,
            model="test:1b",
            runs_dir=tmp_path / "runs",
            timeout=60,
        )

    config = captured["config"]
    assert config.verify_completion is True
    assert config.write_tools_enabled is False
    assert config.max_rounds == 7
    assert result.final_answer == "done"
    assert result.status == "success"
