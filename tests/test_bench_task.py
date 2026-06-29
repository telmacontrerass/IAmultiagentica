"""Tests for benchmark task loading and the BenchTask / VerifierSpec schema."""

from __future__ import annotations

import pytest

from ci2lab.bench.task import BenchTask, VerifierSpec, load_tasks

EXPECTED_TASK_IDS = {
    "cli-01",
    "cli-02",
    "qa-01",
    "qa-02",
    "bug-01",
    "bug-02",
    "feat-01",
}


def test_verifier_from_none_has_no_oracle() -> None:
    spec = VerifierSpec.from_dict(None)
    assert not spec.has_oracle
    assert spec.timeout_seconds == 120


def test_verifier_has_oracle_variants() -> None:
    assert VerifierSpec.from_dict({"answer_contains": ["x"]}).has_oracle
    assert VerifierSpec.from_dict({"command": "true"}).has_oracle
    assert VerifierSpec.from_dict({"fail_to_pass": ["c"]}).has_oracle
    assert not VerifierSpec.from_dict({"forbid_paths": ["x"]}).has_oracle


def test_benchtask_minimal_defaults() -> None:
    task = BenchTask.from_dict({"id": "t", "name": "n", "category": "cli", "prompt": "p"})
    assert task.id == "t"
    assert task.category == "cli"
    assert task.max_rounds == 15
    assert task.git_baseline is False


def test_git_baseline_auto_for_bug_and_feat() -> None:
    bug = BenchTask.from_dict({"id": "b", "name": "n", "category": "bug", "prompt": "p"})
    feat = BenchTask.from_dict({"id": "f", "name": "n", "category": "feat", "prompt": "p"})
    assert bug.git_baseline is True
    assert feat.git_baseline is True


def test_git_baseline_auto_for_forbid_paths() -> None:
    task = BenchTask.from_dict(
        {
            "id": "q",
            "name": "n",
            "category": "qa",
            "prompt": "p",
            "verifier": {"forbid_paths": ["x"], "answer_contains": ["y"]},
        }
    )
    assert task.git_baseline is True


def test_git_baseline_respects_explicit_false() -> None:
    task = BenchTask.from_dict(
        {"id": "b", "name": "n", "category": "bug", "prompt": "p", "git_baseline": False}
    )
    assert task.git_baseline is False


def test_unknown_category_raises() -> None:
    with pytest.raises(ValueError):
        BenchTask.from_dict({"id": "t", "name": "n", "category": "bogus", "prompt": "p"})


def test_load_real_tasks_all_present_and_gradable() -> None:
    tasks = load_tasks()
    ids = {t.id for t in tasks}
    assert ids >= EXPECTED_TASK_IDS
    for task in tasks:
        assert task.verifier.has_oracle, f"{task.id} has no oracle"


def test_load_tasks_filter_by_id() -> None:
    tasks = load_tasks(task_ids=["cli-01"])
    assert [t.id for t in tasks] == ["cli-01"]


def test_load_tasks_missing_dir_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_tasks(tmp_path / "does-not-exist")
