"""Clasificacion de verdicts live (sin LLM)."""

from __future__ import annotations

from ci2lab.evals.harness_write_eval import (
    FAIL_ENVIRONMENT,
    FAIL_HARNESS_PATCH,
    FAIL_HARNESS_POLICY,
    FAIL_MODEL_TOOL_FORMAT,
    FAIL_MODEL_UNDERSTANDING,
    PASS,
    HarnessWriteCaseSpec,
    classify_live_verdict,
)


def _case(case_id: str, **kwargs) -> HarnessWriteCaseSpec:
    return HarnessWriteCaseSpec(case_id=case_id, prompt="p", **kwargs)


def test_classify_pass_when_oracle_ok():
    verdict, _ = classify_live_verdict(
        case=_case("create_file_simple"),
        oracle_ok=True,
        oracle_detail="ok",
        answer="done",
        tool_calls=[{"tool": "write_file", "ok": True, "outcome": "approved"}],
        harness_error=None,
        timed_out=False,
        outside_file_created=False,
    )
    assert verdict == PASS


def test_classify_model_tool_format():
    answer = (
        "Tool call:\n"
        "```json\n"
        '{"name": "write_file", "arguments": BROKEN\n'
        "```"
    )
    verdict, _ = classify_live_verdict(
        case=_case("create_file_simple"),
        oracle_ok=False,
        oracle_detail="falta archivo",
        answer=answer,
        tool_calls=[],
        harness_error=None,
        timed_out=False,
        outside_file_created=False,
    )
    assert verdict == FAIL_MODEL_TOOL_FORMAT


def test_classify_harness_patch_when_tool_ok_oracle_fails():
    verdict, _ = classify_live_verdict(
        case=_case("create_file_simple"),
        oracle_ok=False,
        oracle_detail="contenido mal",
        answer="ok",
        tool_calls=[{"tool": "write_file", "ok": True, "outcome": "approved"}],
        harness_error=None,
        timed_out=False,
        outside_file_created=False,
    )
    assert verdict == FAIL_HARNESS_PATCH


def test_classify_outside_block_pass():
    verdict, _ = classify_live_verdict(
        case=_case("outside_workspace_block", expects_outside_block=True),
        oracle_ok=True,
        oracle_detail="sin archivo externo",
        answer="bloqueado",
        tool_calls=[
            {
                "tool": "write_file",
                "ok": False,
                "outcome": "blocked_by_workspace",
            }
        ],
        harness_error=None,
        timed_out=False,
        outside_file_created=False,
    )
    assert verdict == PASS


def test_classify_outside_leak_policy_fail():
    verdict, _ = classify_live_verdict(
        case=_case("outside_workspace_block", expects_outside_block=True),
        oracle_ok=False,
        oracle_detail="archivo externo",
        answer="ok",
        tool_calls=[],
        harness_error=None,
        timed_out=False,
        outside_file_created=True,
    )
    assert verdict == FAIL_HARNESS_POLICY


def test_classify_timeout_environment():
    verdict, _ = classify_live_verdict(
        case=_case("create_file_simple"),
        oracle_ok=False,
        oracle_detail="",
        answer="",
        tool_calls=[],
        harness_error=None,
        timed_out=True,
        outside_file_created=False,
    )
    assert verdict == FAIL_ENVIRONMENT


def test_classify_no_tools_model_understanding():
    verdict, _ = classify_live_verdict(
        case=_case("create_file_simple"),
        oracle_ok=False,
        oracle_detail="falta hello.txt",
        answer="Ya lo cree.",
        tool_calls=[],
        harness_error=None,
        timed_out=False,
        outside_file_created=False,
    )
    assert verdict == FAIL_MODEL_UNDERSTANDING
