"""Tests for the deterministic multi-agent intent classifier and its wiring."""

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.multiagent.intent import (
    MultiAgentIntent,
    classify_multiagent_intent,
)
from ci2lab.harness.multiagent.orchestrator import run_multi_agent
from ci2lab.harness.multiagent.state import AgentRole, SubAgentResult


def _result(role: AgentRole, output: str, *, attempt: int = 1, **kwargs) -> SubAgentResult:
    return SubAgentResult(
        role=role,
        task=f"{role.value} task",
        output=output,
        attempt=attempt,
        **kwargs,
    )


# --- Pure classifier tests -------------------------------------------------


def test_review_only_blockers_beat_implementation_words():
    decision = classify_multiagent_intent(
        "Review-only task. Please review the change but do not implement it; only inspect."
    )
    assert decision.intent is MultiAgentIntent.REVIEW_ONLY
    assert decision.requires_write is False
    assert "coder" not in decision.allowed_phases
    assert decision.allowed_phases == ["planner", "researcher", "reviewer"]


def test_review_only_negative_constraint():
    decision = classify_multiagent_intent("Only analyze the code, do not change files.")
    assert decision.intent is MultiAgentIntent.REVIEW_ONLY
    assert "coder" not in decision.allowed_phases


def test_conflict_negative_beats_positive():
    decision = classify_multiagent_intent(
        "Review-only task, analyze the code, do not edit files, do not implement."
    )
    assert decision.intent is MultiAgentIntent.REVIEW_ONLY
    assert "coder" not in decision.allowed_phases


def test_document_summary_without_write():
    decision = classify_multiagent_intent("Read the PDF and summarize it, please.")
    assert decision.intent is MultiAgentIntent.DOCUMENT_SUMMARY
    assert decision.requires_write is False
    assert "coder" not in decision.allowed_phases
    assert decision.allowed_phases == ["researcher", "reviewer"]


def test_document_summary_with_explicit_save_includes_coder():
    decision = classify_multiagent_intent(
        "Read the PDF and save the summary into a .txt"
    )
    assert decision.intent is MultiAgentIntent.DOCUMENT_SUMMARY
    assert decision.requires_write is True
    # Persisting output requires an implementer that can write; a read-only flow
    # could never produce the file. The validator is still not needed.
    assert "coder" in decision.allowed_phases
    assert "validator" not in decision.allowed_phases


def test_document_transform_requires_full_flow():
    decision = classify_multiagent_intent("Convert docx to pdf and export it.")
    assert decision.intent is MultiAgentIntent.DOCUMENT_TRANSFORM
    assert decision.requires_write is True
    assert "coder" in decision.allowed_phases


def test_read_only_answer():
    decision = classify_multiagent_intent("Explain what this function does, without editing.")
    assert decision.intent is MultiAgentIntent.READ_ONLY_ANSWER
    assert decision.requires_write is False
    assert "coder" not in decision.allowed_phases


def test_code_change_includes_coder():
    decision = classify_multiagent_intent("implement a fix in orchestrator.py")
    assert decision.intent is MultiAgentIntent.CODE_CHANGE
    assert decision.requires_write is True
    assert decision.allowed_phases == [
        "planner",
        "researcher",
        "coder",
        "validator",
        "reviewer",
    ]


def test_unknown_fallback_is_low_confidence_read_mostly():
    decision = classify_multiagent_intent("Tell me about the repo.")
    assert decision.intent is MultiAgentIntent.UNKNOWN
    assert decision.requires_write is False
    assert decision.confidence == "low"
    assert "coder" not in decision.allowed_phases


# --- Orchestrator wiring tests --------------------------------------------


def _fake_outputs():
    return {
        AgentRole.PLANNER: "Plan output",
        AgentRole.RESEARCHER: "Research output",
        AgentRole.PYTHON_CODER: "Implemented output",
        AgentRole.GENERALIST_CODER: "Implemented output",
        AgentRole.VALIDATOR: "pytest passed",
        AgentRole.REVIEWER: "Review output",
    }


def _run_with_capture(monkeypatch, prompt):
    calls: list[AgentRole] = []
    outputs = _fake_outputs()

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append(role)
        return _result(role, outputs.get(role, "ok"), attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )
    run_multi_agent(
        prompt,
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )
    return calls


def test_review_only_orchestration_skips_coder(monkeypatch):
    calls = _run_with_capture(
        monkeypatch,
        "Review-only task. Analyze the recent change. Do not implement. Only inspect.",
    )
    assert AgentRole.PYTHON_CODER not in calls
    assert AgentRole.GENERALIST_CODER not in calls
    assert AgentRole.VALIDATOR not in calls
    assert calls == [AgentRole.PLANNER, AgentRole.RESEARCHER, AgentRole.REVIEWER]


def test_negative_constraint_review_only_skips_coder(monkeypatch):
    calls = _run_with_capture(monkeypatch, "Only analyze, do not change files.")
    assert AgentRole.GENERALIST_CODER not in calls
    assert AgentRole.VALIDATOR not in calls


def test_document_summary_orchestration_skips_coder(monkeypatch):
    calls = _run_with_capture(monkeypatch, "Read the PDF and summarize it.")
    assert AgentRole.GENERALIST_CODER not in calls
    assert AgentRole.VALIDATOR not in calls
    assert calls == [AgentRole.RESEARCHER, AgentRole.REVIEWER]


def test_document_summary_with_save_runs_coder(monkeypatch):
    # Saving the summary to a file needs a writer: a coder must run (so the file
    # is actually produced), but no validator is required for a document task.
    calls = _run_with_capture(
        monkeypatch, "Read the PDF and save the summary into a .txt"
    )
    assert AgentRole.GENERALIST_CODER in calls
    assert AgentRole.VALIDATOR not in calls


def test_complete_exercise_is_write_intent():
    # Regression: "complete exercise 2" must route to a write flow with a coder.
    # Before, "complete" matched no marker and the task fell to a read-only plan,
    # so nothing was ever written.
    decision = classify_multiagent_intent(
        "read 'exam.pdf', find the instructions for exercise 2 and then complete exercise 2"
    )
    assert decision.requires_write is True
    assert "coder" in decision.allowed_phases


def test_blocked_planner_does_not_abort_run(monkeypatch):
    # Regression: the toolless planner can flail and report "blocked"; that is
    # advisory and must not abort the run — research and implementation still run.
    calls: list[AgentRole] = []
    outputs = _fake_outputs()

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append(role)
        if role is AgentRole.PLANNER:
            return _result(role, "I could not use any tools.", status="blocked")
        return _result(role, outputs.get(role, "ok"), attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )
    answer = run_multi_agent(
        "complete exercise 2 from the notes",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert AgentRole.RESEARCHER in calls
    assert AgentRole.GENERALIST_CODER in calls
    assert "status: blocked" not in answer


def test_code_change_orchestration_runs_coder(monkeypatch):
    # A ".py" file in the request routes to the Python implementer (more precise
    # than the generalist fallback).
    calls = _run_with_capture(monkeypatch, "implement a fix in orchestrator.py")
    assert AgentRole.PLANNER in calls
    assert AgentRole.PYTHON_CODER in calls
    assert AgentRole.VALIDATOR in calls
    assert AgentRole.REVIEWER in calls
