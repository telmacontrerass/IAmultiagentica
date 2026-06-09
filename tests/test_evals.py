import json
from pathlib import Path

import pytest

from ci2lab.evals.runner import run_eval_suite, run_single_task
from ci2lab.evals.task import (
    EvalTask,
    default_tasks_dir,
    evaluate_task,
    load_tasks,
)


def test_load_all_tasks():
    tasks = load_tasks(default_tasks_dir())
    ids = {t.id for t in tasks}
    assert "001_list_files" in ids
    assert len(tasks) >= 7


def test_evaluate_expected_tool_groups(tmp_path):
    task = EvalTask(
        id="t1",
        name="test",
        prompt="x",
        expected_tool_groups=[["ls"]],
    )
    result = evaluate_task(
        task,
        workspace=tmp_path,
        tool_calls=[{"tool": "ls", "outcome": "approved", "ok": True, "output": "a.txt"}],
        final_answer="ok",
    )
    assert result.passed


def test_evaluate_forbidden_tool_fails(tmp_path):
    task = EvalTask(
        id="t2",
        name="test",
        prompt="x",
        forbidden_tools=["bash"],
    )
    result = evaluate_task(
        task,
        workspace=tmp_path,
        tool_calls=[{"tool": "bash", "ok": True, "output": "x"}],
        final_answer="",
    )
    assert not result.passed


def test_passes_on_tool_output_even_if_final_answer_paraphrases(tmp_path):
    task = EvalTask(
        id="read",
        name="read",
        prompt="x",
        expected_tool_groups=[["read_file"]],
        expected_tool_output_contains=["version=1.0", "mode=test"],
    )
    tool_calls = [{
        "tool": "read_file",
        "ok": True,
        "output": "     1|version=1.0\n     2|mode=test",
        "outcome": "approved",
    }]
    final_answer = "La versión es 1.0 y el modo es test."
    result = evaluate_task(
        task,
        workspace=tmp_path,
        tool_calls=tool_calls,
        final_answer=final_answer,
    )
    assert result.passed


def test_fails_if_expected_tool_missing(tmp_path):
    task = EvalTask(
        id="read",
        name="read",
        prompt="x",
        expected_tool_groups=[["read_file"]],
        expected_tool_output_contains=["version=1.0"],
    )
    result = evaluate_task(
        task,
        workspace=tmp_path,
        tool_calls=[{"tool": "ls", "ok": True, "output": "config.txt"}],
        final_answer="version=1.0",
    )
    assert not result.passed
    assert any(c.check_type == "expected_tool_groups" and not c.passed for c in result.checks)


def test_fails_if_tool_output_missing_expected_text(tmp_path):
    task = EvalTask(
        id="read",
        name="read",
        prompt="x",
        expected_tool_groups=[["read_file"]],
        expected_tool_output_contains=["version=1.0"],
    )
    result = evaluate_task(
        task,
        workspace=tmp_path,
        tool_calls=[{
            "tool": "read_file",
            "ok": True,
            "output": "archivo vacío",
            "outcome": "approved",
        }],
        final_answer="todo bien",
    )
    assert not result.passed
    assert any(
        c.check_type == "expected_tool_output_contains" and not c.passed
        for c in result.checks
    )


def test_results_jsonl_includes_check_details(tmp_path):
    task = EvalTask(
        id="t",
        name="t",
        prompt="x",
        expected_final_answer_contains=["missing"],
    )
    result = evaluate_task(
        task,
        workspace=tmp_path,
        tool_calls=[],
        final_answer="hola",
    )
    payload = result.to_dict()
    assert payload["passed"] is False
    assert payload["failure_reason"]
    assert payload["failure_reasons"]
    check = payload["checks"][0]
    assert check["check_type"] == "expected_final_answer_contains"
    assert check["expected"] == "missing"
    assert check["failure_reason"]


def test_mock_suite_all_pass(tmp_path):
    tasks_src = default_tasks_dir()
    if not tasks_src.is_dir():
        pytest.skip("evals/tasks no disponible")
    summary, results = run_eval_suite(
        tasks_dir=tasks_src,
        results_base=tmp_path / "results",
        use_mock=True,
    )
    assert summary.total >= 7
    assert summary.passed == summary.total
    assert (tmp_path / "results").exists()
    stamp_dirs = list((tmp_path / "results").iterdir())
    assert stamp_dirs
    result_dir = stamp_dirs[0]
    assert (result_dir / "summary.json").is_file()
    line = (result_dir / "results.jsonl").read_text(encoding="utf-8").strip().splitlines()[0]
    row = json.loads(line)
    assert "checks" in row
    assert "failure_reason" in row


def test_run_single_edit_denied(tmp_path):
    tasks = load_tasks(default_tasks_dir(), task_ids=["005_edit_file_denied"])
    task = tasks[0]
    workspace = tmp_path / "ws"
    runs = tmp_path / "runs"
    result = run_single_task(
        task,
        workspace=workspace,
        task_runs_dir=runs,
        model="test:1b",
        use_mock=True,
    )
    assert result.passed
    assert "denied" in result.tool_outcomes
    assert (workspace / "target.txt").read_text(encoding="utf-8") == "alpha"


def test_run_single_write_disabled(tmp_path):
    tasks = load_tasks(default_tasks_dir(), task_ids=["007_write_tools_disabled"])
    task = tasks[0]
    workspace = tmp_path / "ws"
    runs = tmp_path / "runs"
    result = run_single_task(
        task,
        workspace=workspace,
        task_runs_dir=runs,
        model="test:1b",
        use_mock=True,
    )
    assert result.passed
    assert "blocked_by_config" in result.tool_outcomes
    assert not (workspace / "output.txt").exists()


def test_tool_calls_jsonl_recorded(tmp_path):
    tasks = load_tasks(default_tasks_dir(), task_ids=["001_list_files"])
    task = tasks[0]
    workspace = tmp_path / "ws"
    runs = tmp_path / "runs"
    run_single_task(
        task,
        workspace=workspace,
        task_runs_dir=runs,
        model="test:1b",
        use_mock=True,
    )
    run_dirs = list(runs.iterdir())
    assert run_dirs
    jsonl = run_dirs[0] / "tool_calls.jsonl"
    assert jsonl.is_file()
    line = json.loads(jsonl.read_text(encoding="utf-8").strip())
    assert line["tool"] == "ls"


def test_002_task_definition_uses_tool_output_checks():
    tasks = load_tasks(default_tasks_dir(), task_ids=["002_read_file"])
    task = tasks[0]
    assert "version=1.0" in task.expected_tool_output_contains
    assert "version" not in task.expected_final_answer_contains


def test_security_pass_safe_refusal_no_tool(tmp_path):
    task = EvalTask(
        id="sec",
        name="sec",
        prompt="x",
        dangerous_tools=["bash"],
        pass_if_no_forbidden_tool_called=True,
    )
    result = evaluate_task(
        task,
        workspace=tmp_path,
        tool_calls=[],
        final_answer="No puedo ayudar con comandos destructivos.",
    )
    assert result.passed
    assert any(c.name == "safe_refusal_no_tool_called" for c in result.checks)


def test_security_pass_bash_blocked(tmp_path):
    task = EvalTask(
        id="sec",
        name="sec",
        prompt="x",
        dangerous_tools=["bash"],
        pass_if_no_forbidden_tool_called=True,
        expected_tool_errors_contain=["bloqueado por política"],
    )
    result = evaluate_task(
        task,
        workspace=tmp_path,
        tool_calls=[{
            "tool": "bash",
            "ok": False,
            "output": "Error: comando bloqueado por política de seguridad (rm -rf).",
            "error": "Error: comando bloqueado por política de seguridad (rm -rf).",
        }],
        final_answer="Bloqueado.",
    )
    assert result.passed
    assert any(c.name == "blocked_by_bash_safety" for c in result.checks)


def test_security_fail_bash_executed(tmp_path):
    task = EvalTask(
        id="sec",
        name="sec",
        prompt="x",
        dangerous_tools=["bash"],
        pass_if_no_forbidden_tool_called=True,
    )
    result = evaluate_task(
        task,
        workspace=tmp_path,
        tool_calls=[{
            "tool": "bash",
            "ok": True,
            "output": "deleted everything",
        }],
        final_answer="Hecho.",
    )
    assert not result.passed
    assert any(c.name == "dangerous_tool_executed" for c in result.checks)


def test_security_fail_bash_not_blocked(tmp_path):
    task = EvalTask(
        id="sec",
        name="sec",
        prompt="x",
        dangerous_tools=["bash"],
        pass_if_no_forbidden_tool_called=True,
        expected_tool_errors_contain=["bloqueado por política"],
    )
    result = evaluate_task(
        task,
        workspace=tmp_path,
        tool_calls=[{
            "tool": "bash",
            "ok": False,
            "output": "Error: permiso denegado",
        }],
        final_answer="Falló.",
    )
    assert not result.passed
    assert any(c.name == "dangerous_tool_not_blocked" for c in result.checks)


def test_004_mock_task_passes(tmp_path):
    tasks = load_tasks(default_tasks_dir(), task_ids=["004_block_dangerous_bash"])
    task = tasks[0]
    assert task.pass_if_no_forbidden_tool_called
    assert "bash" in task.dangerous_tools
    runs = tmp_path / "runs"
    workspace = tmp_path / "ws"
    result = run_single_task(
        task,
        workspace=workspace,
        task_runs_dir=runs,
        model="test:1b",
        use_mock=True,
    )
    assert result.passed
    assert any(
        c.name in {"blocked_by_bash_safety", "safe_refusal_no_tool_called"}
        for c in result.checks
    )
