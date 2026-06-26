"""End-to-end test of the grounded peer-review orchestration.

Uses a fake subagent so no model is needed. The point is to prove the
orchestration enforces groundedness: verified findings reach the report, a
hallucinated quote is quarantined (not presented as a real finding), and a
missing manuscript is refused rather than reviewed from memory.
"""

from dataclasses import replace

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.multiagent import context_budget, manuscript
from ci2lab.harness.multiagent.orchestrator import run_multi_agent
from ci2lab.harness.multiagent.paper_review import ReviewContext
from ci2lab.harness.multiagent.state import AgentRole, SubAgentResult

MANUSCRIPT = """\
We present CI2Lab, a local agent harness for reproducible review.

The system enforces per-phase permissions and logs every tool call for
traceability.

We evaluate the harness on three coding tasks and report the success rate.
"""


def _context():
    return ReviewContext(
        index=manuscript.build_index(MANUSCRIPT),
        paper_meta={"paper_title": "CI2Lab", "field": "AI systems", "target_venue": "Test Venue"},
        reviewer_block="",
        manuscript_source_name="paper.txt",
    )


def _output_for(role: AgentRole, attempt: int) -> str:
    if role == AgentRole.INTAKE_REVIEWER:
        return '[{"claim": "The system logs tool calls", "evidence_type": "manuscript", "evidence_quote": "logs every tool call for traceability", "anchor": "A2"}]'
    if role == AgentRole.SCOPE_REVIEWER:
        return '[{"claim": "Plausibly fits a systems venue", "evidence_type": "manuscript", "evidence_quote": "local agent harness for reproducible review", "anchor": "A1"}]'
    if role == AgentRole.NOVELTY_REVIEWER:
        if attempt >= 2:
            # Re-ground attempt re-asserts the ungroundable claim -> quarantined.
            return '[{"claim": "Beats all baselines", "evidence_type": "manuscript", "evidence_quote": "we outperform every prior system by a wide margin", "anchor": "A9"}]'
        return (
            '[{"claim": "Reproducible by design", "evidence_type": "manuscript", '
            '"evidence_quote": "logs every tool call for traceability", "anchor": "A2"},'
            '{"claim": "Beats all baselines", "evidence_type": "manuscript", '
            '"evidence_quote": "we outperform every prior system by a wide margin", "anchor": "A9"}]'
        )
    if role == AgentRole.METHODOLOGY_REVIEWER:
        return '[{"claim": "No significance testing reported", "evidence_type": "absence", "absence_terms": ["statistical significance", "p-value"]}]'
    if role == AgentRole.GROUNDEDNESS_VERIFIER:
        return "[]"  # no per-finding objection -> keep all code-verified findings
    if role == AgentRole.REVISION_PLANNER:
        return "PAPER REVIEW REPORT\n1. Summary\nThe paper logs every tool call.\n10. Verdict: major revision"
    return "[]"  # field/adversarial/format produce nothing here


def _patch(monkeypatch):
    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        return SubAgentResult(
            role=role,
            task=f"{role.value} task",
            output=_output_for(role, attempt),
            attempt=attempt,
            tool_calls=[],
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent", fake_run_subagent
    )


def test_grounded_review_keeps_verified_and_quarantines_hallucination(monkeypatch):
    _patch(monkeypatch)
    answer = run_multi_agent(
        "peer review this paper",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False, multiagent_flow="paper_review"),
        review_context=_context(),
    )

    assert "PAPER REVIEW REPORT" in answer
    assert "Grounded findings" in answer
    # A real quote is verified and surfaced with its anchor.
    assert "logs every tool call for traceability" in answer
    # The true absence claim is verified.
    assert "No significance testing reported" in answer
    assert "confirmed absent" in answer.lower()

    # The hallucinated claim is quarantined, not presented as a real finding.
    quarantine_marker = "DO NOT send"
    assert quarantine_marker in answer
    quarantine_section = answer.split(quarantine_marker, 1)[1]
    assert "Beats all baselines" in quarantine_section
    # Its invented quote must never appear as verified evidence.
    grounded_section = answer.split("Grounded findings", 1)[1].split(quarantine_marker, 1)[0]
    assert "we outperform every prior system" not in grounded_section

    assert "Coverage & limitations" in answer


def test_unverifiable_external_citation_goes_to_manual_check(monkeypatch):
    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        out = "[]"
        if role == AgentRole.NOVELTY_REVIEWER:
            out = (
                '[{"claim": "Overlaps with prior work", "evidence_type": "external", '
                '"external_url": "https://paywalled.example/article"}]'
            )
        elif role == AgentRole.REVISION_PLANNER:
            out = "PAPER REVIEW REPORT\n10. Verdict: major revision"
        return SubAgentResult(role=role, task="t", output=out, attempt=attempt, tool_calls=[])

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent", fake_run_subagent
    )
    answer = run_multi_agent(
        "peer review this paper",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False, multiagent_flow="paper_review"),
        review_context=_context(),
    )

    # An uncheckable citation goes to "could not verify", NOT the "do not send" pile.
    assert "Could not verify" in answer
    manual = answer.split("Could not verify", 1)[1]
    assert "paywalled.example" in manual
    if "DO NOT send" in answer:
        quarantine = answer.split("DO NOT send", 1)[1]
        assert "Overlaps with prior work" not in quarantine


def test_small_context_model_aborts_and_recommends_bigger(monkeypatch):
    calls = []

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append(role)
        return SubAgentResult(role=role, task="t", output="[]", attempt=attempt, tool_calls=[])

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent", fake_run_subagent
    )
    tiny = replace(default_selection("test:1b"), context_length=2048)
    answer = run_multi_agent(
        "peer review this paper",
        tiny,
        config=AgentConfig(cwd=".", run_log_enabled=False, multiagent_flow="paper_review"),
        review_context=_context(),
    )
    # Aborts BEFORE running any reviewer — never grabs more than it can take.
    assert calls == []
    assert "NOT POSSIBLE WITH THIS MODEL" in answer
    assert "models recommend" in answer


def test_garbage_output_triggers_quality_abort(monkeypatch):
    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        # Unstructured prose for every role: the model cannot follow the contract.
        return SubAgentResult(
            role=role,
            task="t",
            output="I am not sure but the paper seems fine overall I think",
            attempt=attempt,
            tool_calls=[],
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent", fake_run_subagent
    )
    answer = run_multi_agent(
        "peer review this paper",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False, multiagent_flow="paper_review"),
        review_context=_context(),
    )
    assert "WOULD NOT BE RELIABLE" in answer
    assert "PAPER REVIEW REPORT" not in answer


def test_long_manuscript_is_reviewed_chunk_by_chunk(monkeypatch):
    # A manuscript that needs several chunks: each lens must run once per chunk.
    big = manuscript.build_index("Section text alpha beta gamma delta. " * 600)
    ctx = ReviewContext(index=big, paper_meta={}, manuscript_source_name="big.txt")
    feas = context_budget.assess_feasibility(big, 8192)
    assert feas.feasible and feas.n_chunks > 1  # precondition for the test

    intake_calls = []

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        if role == AgentRole.INTAKE_REVIEWER:
            intake_calls.append(task_prompt)
        out = "[]"
        if role in {
            AgentRole.INTAKE_REVIEWER,
            AgentRole.METHODOLOGY_REVIEWER,
        }:
            # A truly-absent term -> verified, no re-ground, one call per chunk.
            out = '[{"claim": "No power analysis", "evidence_type": "absence", "absence_terms": ["statistical power analysis"]}]'
        elif role == AgentRole.REVISION_PLANNER:
            out = "PAPER REVIEW REPORT\n10. Verdict: major revision"
        return SubAgentResult(role=role, task="t", output=out, attempt=attempt, tool_calls=[])

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent", fake_run_subagent
    )
    answer = run_multi_agent(
        "peer review this paper",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False, multiagent_flow="paper_review"),
        review_context=ctx,
    )
    # Intake ran once per chunk -> the whole manuscript was covered.
    assert len(intake_calls) == feas.n_chunks
    assert "PAPER REVIEW REPORT" in answer
    assert "No power analysis" in answer


def test_review_without_manuscript_is_refused(monkeypatch):
    _patch(monkeypatch)
    answer = run_multi_agent(
        "peer review this paper",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False, multiagent_flow="paper_review"),
        review_context=None,
    )
    assert "NOT POSSIBLE" in answer
    assert "PAPER REVIEW REPORT" not in answer


def test_empty_manuscript_is_refused(monkeypatch):
    _patch(monkeypatch)
    answer = run_multi_agent(
        "peer review this paper",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False, multiagent_flow="paper_review"),
        review_context=ReviewContext(index=manuscript.build_index("")),
    )
    assert "NOT POSSIBLE" in answer
