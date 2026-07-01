"""Tests for the opt-in completion verifier."""

from types import SimpleNamespace
from unittest.mock import patch

from ci2lab.harness import default_selection
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.query.verifier import (
    VerificationVerdict,
    _verdict_is_failure,
    parse_verdict,
    verify_completion,
)
from ci2lab.harness.types import AgentConfig, ToolResult


def _write_call(cid, path, content):
    return LLMResponse(
        content="",
        tool_calls=[
            {
                "id": cid,
                "function": {
                    "name": "write_file",
                    "arguments": f'{{"path": "{path}", "content": "{content}"}}',
                },
            }
        ],
    )


def test_verdict_parsing_is_conservative():
    assert _verdict_is_failure("FAIL\n- did not create file") is True
    assert _verdict_is_failure("fail: nothing was written") is True
    assert _verdict_is_failure("PASS") is False
    assert _verdict_is_failure("") is False
    # An explained pass that mentions the word fail must not be read as failure.
    assert _verdict_is_failure("PASS - no FAIL conditions found") is False


def test_parse_verdict_extracts_structured_verdict():
    text = (
        "Here is my verdict:\n"
        "```json\n"
        '{"passed": false, "confidence": "high", '
        '"criteria": [{"criterion": "file exists", "met": true}, '
        '{"criterion": "content correct", "met": false, "evidence": "line missing"}], '
        '"gaps": ["the required line is missing from out.txt"]}\n'
        "```\n"
    )
    verdict = parse_verdict(text)
    assert verdict is not None
    assert verdict.passed is False
    assert verdict.confidence == "high"
    assert verdict.gaps == ("the required line is missing from out.txt",)
    assert verdict.is_actionable_failure is True


def test_parse_verdict_returns_none_for_unstructured_output():
    assert parse_verdict("The work looks fine to me, PASS.") is None
    assert parse_verdict("") is None


def test_low_confidence_failure_is_not_actionable():
    # A weak/uncertain verifier must not block a genuinely-finished task.
    verdict = VerificationVerdict(
        passed=False, confidence="low", criteria=(), gaps=("maybe wrong",)
    )
    assert verdict.is_actionable_failure is False


def test_failure_without_gaps_harvests_unmet_criteria():
    text = (
        '{"passed": false, "confidence": "medium", '
        '"criteria": [{"criterion": "tests pass", "met": false}], "gaps": []}'
    )
    verdict = parse_verdict(text)
    assert verdict is not None
    assert verdict.gaps == ("tests pass",)
    assert verdict.is_actionable_failure is True


def _fake_subagent(output, status="completed"):
    return SimpleNamespace(status=status, output=output)


def test_verify_completion_blocks_on_confident_structured_failure():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", run_log_enabled=False)
    verdict_json = (
        '{"passed": false, "confidence": "high", "criteria": [], "gaps": ["out.txt is empty"]}'
    )
    with patch(
        "ci2lab.harness.multiagent.runner.run_subagent",
        return_value=_fake_subagent(verdict_json),
    ):
        issues = verify_completion(config, selection, "create out.txt", ["write_file out.txt"])
    assert issues is not None
    assert "out.txt is empty" in issues


def test_verify_completion_passes_on_structured_pass():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", run_log_enabled=False)
    verdict_json = '{"passed": true, "confidence": "high", "criteria": [], "gaps": []}'
    with patch(
        "ci2lab.harness.multiagent.runner.run_subagent",
        return_value=_fake_subagent(verdict_json),
    ):
        issues = verify_completion(config, selection, "create out.txt", ["write_file out.txt"])
    assert issues is None


def test_verify_completion_leans_pass_on_low_confidence():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", run_log_enabled=False)
    verdict_json = '{"passed": false, "confidence": "low", "gaps": ["not sure"]}'
    with patch(
        "ci2lab.harness.multiagent.runner.run_subagent",
        return_value=_fake_subagent(verdict_json),
    ):
        issues = verify_completion(config, selection, "create out.txt", ["write_file out.txt"])
    assert issues is None


def test_verify_completion_falls_back_to_first_line_fail():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", run_log_enabled=False)
    with patch(
        "ci2lab.harness.multiagent.runner.run_subagent",
        return_value=_fake_subagent("FAIL\n- the file is missing entirely"),
    ):
        issues = verify_completion(config, selection, "create out.txt", ["write_file out.txt"])
    assert issues is not None
    assert "missing" in issues


def test_verify_completion_uses_validator_role_when_auto_confirm():
    # Execution grounding: a non-interactive run gets the bash-capable VALIDATOR;
    # an interactive run gets the read-only REVIEWER (no surprise prompts).
    from ci2lab.harness.multiagent.state import AgentRole

    selection = default_selection("test:1b")
    verdict_json = '{"passed": true, "confidence": "high", "gaps": []}'
    for auto_confirm, expected in ((True, AgentRole.VALIDATOR), (False, AgentRole.REVIEWER)):
        config = AgentConfig(cwd=".", run_log_enabled=False, auto_confirm=auto_confirm)
        with patch(
            "ci2lab.harness.multiagent.runner.run_subagent",
            return_value=_fake_subagent(verdict_json),
        ) as mock_run:
            verify_completion(config, selection, "create out.txt", ["write_file out.txt"])
        assert mock_run.call_args.args[0] is expected


def test_verifier_failure_injects_fix_message_then_finishes():
    selection = default_selection("test:1b")
    # Large window so context summarization (which consumes a mocked chat
    # response) never fires and shifts the scripted call sequence; this test is
    # about the verifier fix flow, not about context management.
    selection.context_length = 1_000_000
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        verify_completion=True,
    )
    # Round 1: write a file then claim done. Verifier FAILs. Round 2: write again
    # and claim done. Verifier PASSes -> finish.
    round1 = _write_call("c1", "out.txt", "v1")
    done1 = LLMResponse(content="Done, wrote out.txt.", tool_calls=[])
    round2 = _write_call("c2", "out.txt", "v2")
    done2 = LLMResponse(content="Fixed and wrote out.txt.", tool_calls=[])

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            side_effect=lambda call, _c: ToolResult(
                tool_name=call.name, content="Wrote out.txt", is_error=False, call_id=call.call_id
            ),
        ),
        patch(
            "ci2lab.harness.query.loop.verify_completion",
            side_effect=["FAIL\n- the content is wrong", None],
        ) as mock_verify,
    ):
        client = MockClient.return_value
        client.chat.side_effect = [round1, done1, round2, done2]
        result = run_agentless(client, "create out.txt with the right content", selection, config)

    assert mock_verify.call_count == 2  # verified after each "done"
    assert "wrote out.txt" in result.lower()
    # The fix instruction was injected into the conversation after the first FAIL.
    all_sent = [m for call in client.chat.call_args_list for m in call.args[0]]
    assert any("independent verifier" in str(m.get("content", "")).lower() for m in all_sent)


def test_verifier_not_run_without_effectful_work():
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        verify_completion=True,
    )
    answer = LLMResponse(content="The loop lives in loop.py.", tool_calls=[])
    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.verify_completion") as mock_verify,
    ):
        client = MockClient.return_value
        client.chat.return_value = answer
        run_agentless(client, "where is the loop?", selection, config)

    mock_verify.assert_not_called()  # no successful mutation -> nothing to verify


def test_verifier_runs_on_command_evidence_without_mutation():
    # A task can be "done" via a command (ran the tests) with no file mutation;
    # completion verification must still fire on that runtime evidence.
    selection = default_selection("test:1b")
    selection.context_length = 1_000_000
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        verify_completion=True,
    )
    run_cmd = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {"name": "bash", "arguments": '{"command": "pytest -q"}'},
            }
        ],
    )
    done = LLMResponse(content="Ran the tests; all pass.", tool_calls=[])
    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            side_effect=lambda call, _c: ToolResult(
                tool_name=call.name, content="3 passed", is_error=False, call_id=call.call_id
            ),
        ),
        patch("ci2lab.harness.query.loop.verify_completion", return_value=None) as mock_verify,
    ):
        client = MockClient.return_value
        client.chat.side_effect = [run_cmd, done]
        run_agentless(client, "run the tests and confirm they pass", selection, config)

    mock_verify.assert_called_once()


def test_verifier_off_by_default():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    assert config.verify_completion is False
    write = _write_call("c1", "out.txt", "v1")
    done = LLMResponse(content="Wrote out.txt.", tool_calls=[])
    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            side_effect=lambda call, _c: ToolResult(
                tool_name=call.name, content="Wrote out.txt", is_error=False, call_id=call.call_id
            ),
        ),
        patch("ci2lab.harness.query.loop.verify_completion") as mock_verify,
    ):
        client = MockClient.return_value
        client.chat.side_effect = [write, done]
        run_agentless(client, "create out.txt", selection, config)

    mock_verify.assert_not_called()


def run_agentless(client, prompt, selection, config):
    """Run run_agent with LLMClient already patched on the loop module."""
    from ci2lab.harness import run_agent

    return run_agent(prompt, selection, config=config)
