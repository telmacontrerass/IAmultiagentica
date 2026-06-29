"""Tests for the opt-in completion verifier."""

from unittest.mock import patch

from ci2lab.harness import default_selection
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.query.verifier import _verdict_is_failure
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
