"""Tests for the Harbor results aggregator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ci2lab.bench.harbor_report import (
    TrialRecord,
    load_job_dir,
    main,
    render_markdown_table,
    summarize_condition,
)


def _write_trial(
    job: Path,
    task_id: str,
    trial: str,
    *,
    reward: float | None,
    prompt: int = 100,
    completion: int = 50,
    quality: dict[str, Any] | None = None,
) -> None:
    trial_dir = job / task_id / trial
    trial_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "task_id": task_id,
        "agent_result": {
            "n_input_tokens": prompt,
            "n_output_tokens": completion,
            "metadata": {"tool_call_quality": quality} if quality else {},
        },
    }
    if reward is not None:
        payload["verifier_result"] = {"rewards": {"reward": reward}}
    (trial_dir / "results.json").write_text(json.dumps(payload), encoding="utf-8")


def _quality(**kwargs: int) -> dict[str, Any]:
    base = {
        "attempts": 0,
        "raw_correct": 0,
        "effective_correct": 0,
        "repaired": 0,
        "malformed": 0,
        "hallucinated_tool": 0,
        "invalid_arguments": 0,
        "execution_error": 0,
    }
    base.update(kwargs)
    return base


def test_load_job_dir_reads_trials_and_skips_the_root_aggregate(tmp_path: Path) -> None:
    job = tmp_path / "ci2lab"
    job.mkdir()
    # The job-root aggregate must not be mistaken for a trial.
    (job / "results.json").write_text(json.dumps({"evals": {}}), encoding="utf-8")
    _write_trial(job, "task-a", "1", reward=1.0)
    _write_trial(job, "task-a", "2", reward=0.0)

    records = load_job_dir(job)
    assert len(records) == 2
    assert {r.task_id for r in records} == {"task-a"}
    assert sorted(bool(r.resolved) for r in records) == [False, True]


def test_pass_at_1_is_averaged_over_tasks(tmp_path: Path) -> None:
    job = tmp_path / "j"
    job.mkdir()
    # task-a solved 1 of 2; task-b solved 2 of 2  ->  pass@1 = (0.5 + 1.0)/2
    _write_trial(job, "task-a", "1", reward=1.0)
    _write_trial(job, "task-a", "2", reward=0.0)
    _write_trial(job, "task-b", "1", reward=1.0)
    _write_trial(job, "task-b", "2", reward=1.0)

    summary = summarize_condition("ci2lab", load_job_dir(job))
    assert summary.tasks == 2
    assert summary.pass_at_1 == 0.75
    # pass^k: only task-b succeeded on every attempt.
    assert summary.pass_hat_k == 0.5
    assert summary.pass_at_1_ci is not None


def test_unreadable_trials_are_counted_not_failed(tmp_path: Path) -> None:
    # A trial with no reward is broken, not failed. Counting it as a failure would
    # bias pass@1 down and hide a broken pipeline.
    job = tmp_path / "j"
    job.mkdir()
    _write_trial(job, "task-a", "1", reward=1.0)
    _write_trial(job, "task-a", "2", reward=None)

    summary = summarize_condition("ci2lab", load_job_dir(job))
    assert summary.unreadable == 1
    assert summary.trials == 2
    assert summary.pass_at_1 == 1.0  # the one readable trial solved its task

    table = render_markdown_table([summary])
    assert "unreadable" in table


def test_tool_call_quality_is_summed_across_trials(tmp_path: Path) -> None:
    job = tmp_path / "j"
    job.mkdir()
    _write_trial(
        job,
        "task-a",
        "1",
        reward=1.0,
        quality=_quality(attempts=10, raw_correct=6, effective_correct=8, repaired=2),
    )
    _write_trial(
        job,
        "task-a",
        "2",
        reward=0.0,
        quality=_quality(attempts=10, raw_correct=4, effective_correct=6, repaired=2, malformed=4),
    )

    summary = summarize_condition("ci2lab", load_job_dir(job))
    q = summary.quality
    assert q.attempts == 20
    assert q.raw_correct == 10
    assert q.effective_correct == 14
    assert q.raw_correctness_rate == 0.5
    assert q.effective_correctness_rate == 0.7
    assert q.repair_rate == 0.2


def test_tokens_per_solved_trial(tmp_path: Path) -> None:
    job = tmp_path / "j"
    job.mkdir()
    _write_trial(job, "task-a", "1", reward=1.0, prompt=100, completion=50)
    _write_trial(job, "task-a", "2", reward=0.0, prompt=100, completion=50)

    summary = summarize_condition("ci2lab", load_job_dir(job))
    assert summary.total_tokens == 300
    assert summary.solved_trials == 1
    assert summary.tokens_per_solved == 300.0


def test_condition_with_no_tool_trace_renders_blank_not_zero() -> None:
    # deepagents emits no trajectory; its tool columns must not read as a real 0%.
    summary = summarize_condition(
        "deepagents",
        [TrialRecord(task_id="t", resolved=True, prompt_tokens=1, completion_tokens=1)],
    )
    table = render_markdown_table([summary])
    assert "no tool-call trace" in table
    assert summary.quality.attempts == 0


def test_no_solved_trials_has_no_tokens_per_solved() -> None:
    summary = summarize_condition("x", [TrialRecord(task_id="t", resolved=False, prompt_tokens=10)])
    assert summary.tokens_per_solved is None


def test_table_is_ascii_so_a_cp1252_console_cannot_mangle_it() -> None:
    # The table gets pasted into the paper; an en/em dash becomes mojibake on a
    # cp1252 terminal, so every cell must stay ASCII.
    summary = summarize_condition("deepagents", [TrialRecord(task_id="t", resolved=None)])
    table = render_markdown_table([summary])
    table.encode("ascii")  # raises UnicodeEncodeError if a dash sneaks back in


def test_main_renders_a_table(tmp_path: Path, capsys: Any) -> None:
    job = tmp_path / "ci2lab"
    job.mkdir()
    _write_trial(job, "task-a", "1", reward=1.0, quality=_quality(attempts=4, raw_correct=4))

    assert main([f"ci2lab={job}"]) == 0
    out = capsys.readouterr().out
    assert "| ci2lab |" in out
    assert "pass@1" in out


def test_main_rejects_a_missing_directory(tmp_path: Path, capsys: Any) -> None:
    assert main([str(tmp_path / "nope")]) == 2


def test_main_with_no_args_is_an_error(capsys: Any) -> None:
    assert main([]) == 2
