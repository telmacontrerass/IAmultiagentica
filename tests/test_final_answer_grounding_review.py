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

    result = review_final_answer(
        "I cannot verify the current CEO from the available evidence.", ledger
    )

    assert result.ok is True


def test_mutation_claim_requires_successful_mutating_tool():
    ledger = EvidenceLedger(user_prompt="create out.txt")
    failed = review_final_answer("Created out.txt.", ledger)
    ledger.add("write_file", {"path": "out.txt"}, "Wrote out.txt", ok=True)
    passed = review_final_answer("Created out.txt.", ledger)

    assert failed.ok is False
    assert passed.ok is True


def test_no_regression_claim_requires_broad_check_after_edit():
    # Reproduces the qwen3 bug-02 false positive: the agent edits a shared
    # function, runs ONLY the single test named in the prompt, then claims it
    # broke nothing else. A scoped run cannot ground that claim.
    ledger = EvidenceLedger(user_prompt="Fix the bug without breaking other behaviour.")
    ledger.add("edit_file", {"path": "rangeutil.py"}, "1 replacement", ok=True)
    ledger.add(
        "bash",
        {"command": "python -m pytest -q test_inclusive.py"},
        "1 passed",
        ok=True,
    )

    result = review_final_answer(
        "I fixed the bug in rangeutil.py. No other functionality was broken.", ledger
    )

    assert result.ok is False
    assert "no regressions" in result.instruction.lower()


def test_no_regression_claim_grounded_by_full_suite_run():
    ledger = EvidenceLedger(user_prompt="Fix the bug without breaking other behaviour.")
    ledger.add("edit_file", {"path": "rangeutil.py"}, "1 replacement", ok=True)
    ledger.add("bash", {"command": "python -m pytest -q"}, "2 passed", ok=True)

    result = review_final_answer(
        "I fixed the bug in rangeutil.py. No other functionality was broken.", ledger
    )

    assert result.ok is True


def test_no_regression_phrasing_without_mutation_is_allowed():
    # A pure Q&A answer that happens to mention "without breaking" must not be
    # blocked — the rule only guards claims made after an actual code change.
    ledger = EvidenceLedger(user_prompt="How can I refactor without breaking anything?")

    result = review_final_answer(
        "You can refactor without breaking other behaviour by adding tests first.", ledger
    )

    assert result.ok is True


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
        "default groundedness review blocked" in str(m.get("content", "")).lower() for m in all_sent
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


def test_invented_code_token_requires_evidence():
    # An identifier-shaped code stated in the answer must exist in the prompt
    # or in this turn's tool evidence — confabulated codes are exactly how a
    # wrong answer masquerades as a finding.
    ledger = EvidenceLedger(user_prompt="Report the fatal ERR-XXXX code from app.log")
    ledger.add("read_file", {"path": "app.log"}, "FATAL lost code=ERR-4219 host=db", ok=True)

    invented = review_final_answer("The fatal error code is ERR-2048.", ledger)
    grounded = review_final_answer("The fatal error code is ERR-4219.", ledger)

    assert invented.ok is False
    assert "ERR-2048" in " ".join(invented.issues)
    assert grounded.ok is True


def test_code_tokens_allowed_in_chat_and_for_known_standards():
    # No tool records -> ordinary conversation; code-shaped tokens are prose.
    chat = EvidenceLedger(user_prompt="explain hashing")
    assert review_final_answer("SHA-256 is a hash function.", chat).ok is True

    # Well-known public identifiers are world knowledge, not workspace facts.
    ledger = EvidenceLedger(user_prompt="check the date handling in this repo")
    ledger.add("read_file", {"path": "dates.py"}, "strftime('%Y-%m-%d')", ok=True)
    assert review_final_answer("Dates follow the ISO-8601 format.", ledger).ok is True


def test_strip_code_fence_peels_only_a_wrapping_fence():
    from ci2lab.harness.query.loop import _strip_code_fence

    assert _strip_code_fence("```markdown\nProblema 1\nx = 2\n```") == "Problema 1\nx = 2"
    # No wrapping fence: text is returned untouched (only trimmed).
    assert _strip_code_fence("Problema 1\nx = 2\n") == "Problema 1\nx = 2"
    # An inner fence that does not wrap the whole text is preserved.
    body = "Intro\n```\ncode\n```\nOutro"
    assert _strip_code_fence(body) == body


def test_transcription_turn_skips_final_answer_review():
    # A pure transcription is grounded in the attached document by construction;
    # the groundedness review (which would flag "version" as a current-fact
    # claim and re-prompt) must not run, so it finalizes in a single call. The
    # prompt names no workspace path, so the separate "no tool evidence" nudge
    # stays silent and the review skip is the only thing under test.
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = LLMResponse(
            content="## Transcription\nProblema 1: version 2 of the formula.",
            tool_calls=[],
        )
        result = run_agent("Transcribe the handwritten notes", selection, config=config)

    assert "version 2 of the formula" in result
    assert "cannot safely confirm" not in result.lower()
    assert MockClient.return_value.chat.call_count == 1
