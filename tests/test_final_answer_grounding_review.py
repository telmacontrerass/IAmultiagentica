from unittest.mock import patch

from ci2lab.harness import AgentConfig, default_selection, run_agent
from ci2lab.harness.grounding_review import EvidenceLedger, review_final_answer
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.types import ToolResult


def test_current_fact_requires_evidence():
    ledger = EvidenceLedger(user_prompt="who is the current CEO?")

    result = review_final_answer("The current CEO is Ada Example.", ledger)

    assert result.ok is False
    assert "current" in result.instruction.lower()


def test_uncertainty_is_allowed_without_evidence():
    ledger = EvidenceLedger(user_prompt="who is the current CEO?")

    result = review_final_answer("I cannot verify the current CEO from the available evidence.", ledger)

    assert result.ok is True


def test_mutation_claim_requires_successful_mutating_tool():
    ledger = EvidenceLedger(user_prompt="create out.txt")
    failed = review_final_answer("Created out.txt.", ledger)
    ledger.add("write_file", {"path": "out.txt"}, "Wrote out.txt", ok=True)
    passed = review_final_answer("Created out.txt.", ledger)

    assert failed.ok is False
    assert passed.ok is True


def test_loop_reviews_final_answer_before_accepting_ungrounded_repo_claim():
    selection = default_selection("test:1b")
    selection.context_length = 1_000_000
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    ungrounded = LLMResponse(
        content="The project uses FastAPI in ci2lab/ui/server.py.",
        tool_calls=[],
    )
    read = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path": "ci2lab/ui/server.py", "limit": 20}',
                },
            }
        ],
    )
    grounded = LLMResponse(content="ci2lab/ui/server.py defines the UI server.", tool_calls=[])

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            return_value=ToolResult(
                tool_name="read_file",
                content="from http.server import ThreadingHTTPServer\n",
                is_error=False,
                call_id="c1",
            ),
        ),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [ungrounded, read, grounded]
        result = run_agent("What does the UI server use?", selection, config=config)

    assert result == "ci2lab/ui/server.py defines the UI server."
    all_sent = [m for call in client.chat.call_args_list for m in call.args[0]]
    assert any(
        "default groundedness review blocked" in str(m.get("content", "")).lower()
        for m in all_sent
    )


def test_final_answer_review_can_be_disabled():
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        verify_final_answer=False,
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = LLMResponse(
            content="The project uses FastAPI in ci2lab/ui/server.py.",
            tool_calls=[],
        )
        result = run_agent("What does the UI server use?", selection, config=config)

    assert "FastAPI" in result


def test_final_answer_review_runs_even_without_tool_support():
    selection = default_selection("test:1b")
    selection.supports_tools = False
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    ungrounded = LLMResponse(
        content="The current CEO is Ada Example.",
        tool_calls=[],
    )
    cautious = LLMResponse(
        content="I cannot verify the current CEO from the available evidence.",
        tool_calls=[],
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [ungrounded, cautious]
        result = run_agent("Who is the current CEO?", selection, config=config)

    assert "cannot verify" in result.lower()
    assert client.chat.call_count == 2


def test_final_answer_review_returns_guarded_fallback_when_still_unsupported():
    selection = default_selection("test:1b")
    selection.context_length = 1_000_000
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        max_rounds=1,
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = LLMResponse(
            content="The current CEO is Ada Example.",
            tool_calls=[],
        )
        result = run_agent("Who is the current CEO?", selection, config=config)

    assert "cannot safely confirm" in result.lower()
    assert "unverified claim" in result.lower()
