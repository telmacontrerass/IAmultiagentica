"""Tests for the benchmark verifier (answer / command / forbid-path grading).

These exercise the oracle in isolation — no agent or Ollama is involved. The
command-based tests need a Python interpreter on PATH; the bug-01 end-to-end
test additionally validates that the shipped fixture actually grades correctly.
"""

from __future__ import annotations

import shutil

import pytest

from ci2lab.bench.task import BenchTask, load_tasks, setup_workspace
from ci2lab.bench.verifier import verify

_PYTHON = "python" if shutil.which("python") else ("python3" if shutil.which("python3") else None)


def _task(verifier: dict, **extra: object) -> BenchTask:
    data: dict = {"id": "t", "name": "n", "category": "cli", "prompt": "p", "verifier": verifier}
    data.update(extra)
    return BenchTask.from_dict(data)


def test_answer_contains_pass(tmp_path) -> None:
    task = _task({"answer_contains": ["ERR-7731"]})
    assert verify(task, workspace=tmp_path, final_answer="the code is ERR-7731.").solved


def test_answer_contains_fail(tmp_path) -> None:
    task = _task({"answer_contains": ["ERR-7731"]})
    assert not verify(task, workspace=tmp_path, final_answer="nothing here").solved


def test_answer_contains_case_insensitive(tmp_path) -> None:
    task = _task({"answer_contains": ["err-7731"]})
    assert verify(task, workspace=tmp_path, final_answer="ERR-7731").solved


def test_answer_contains_ordered(tmp_path) -> None:
    task = _task({"answer_contains": ["a.py", "b.py", "c.py"], "answer_contains_ordered": True})
    assert verify(task, workspace=tmp_path, final_answer="a.py then b.py then c.py").solved
    assert not verify(task, workspace=tmp_path, final_answer="c.py b.py a.py").solved


def test_forbid_paths(tmp_path) -> None:
    task = _task({"answer_contains": ["x"], "forbid_paths": ["tests/"]})
    blocked = verify(task, workspace=tmp_path, final_answer="x", changed_paths=["tests/test_a.py"])
    allowed = verify(task, workspace=tmp_path, final_answer="x", changed_paths=["src/a.py"])
    assert not blocked.solved
    assert allowed.solved


def test_no_oracle_is_unsolved(tmp_path) -> None:
    task = _task({})
    assert not verify(task, workspace=tmp_path, final_answer="anything").solved


@pytest.mark.skipif(_PYTHON is None, reason="no python interpreter on PATH")
def test_command_exit_code(tmp_path) -> None:
    ok = _task({"command": f'{_PYTHON} -c "import sys; sys.exit(0)"'})
    bad = _task({"command": f'{_PYTHON} -c "import sys; sys.exit(1)"'})
    assert verify(ok, workspace=tmp_path, final_answer="").solved
    assert not verify(bad, workspace=tmp_path, final_answer="").solved


@pytest.mark.skipif(shutil.which("python") is None, reason="bug-01 fixture invokes 'python'")
def test_bug01_fixture_grades_correctly(tmp_path) -> None:
    """The shipped bug-01 oracle must fail on the buggy code and pass on a fix."""
    task = load_tasks(task_ids=["bug-01"])[0]
    workspace = tmp_path / "ws"
    setup_workspace(workspace, task.workspace_setup)
    setup_workspace(workspace, task.hidden_setup)

    # The seeded (buggy) discount.py must not satisfy the oracle.
    buggy = verify(task, workspace=workspace, final_answer="", changed_paths=[])
    assert not buggy.solved

    # Apply the intended one-line fix (>= 100 -> > 100) and re-grade.
    (workspace / "discount.py").write_text(
        "def apply_discount(price, pct):\n"
        "    if pct < 0 or pct > 100:\n"
        "        raise ValueError('pct out of range: ' + str(pct))\n"
        "    return price - price * pct / 100\n",
        encoding="utf-8",
    )
    fixed = verify(task, workspace=workspace, final_answer="", changed_paths=[])
    assert fixed.solved, fixed.failure_reasons
