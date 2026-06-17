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


def test_review_only_spanish_negative_constraint():
    decision = classify_multiagent_intent("Solo analiza el código, no cambies archivos.")
    assert decision.intent is MultiAgentIntent.REVIEW_ONLY
    assert "coder" not in decision.allowed_phases


def test_conflict_negative_beats_positive():
    decision = classify_multiagent_intent(
        "Review-only task, analyze the code, do not edit files, do not implement."
    )
    assert decision.intent is MultiAgentIntent.REVIEW_ONLY
    assert "coder" not in decision.allowed_phases


def test_document_summary_without_write():
    decision = classify_multiagent_intent("Lee el PDF y resúmelo, por favor.")
    assert decision.intent is MultiAgentIntent.DOCUMENT_SUMMARY
    assert decision.requires_write is False
    assert "coder" not in decision.allowed_phases
    assert decision.allowed_phases == ["researcher", "reviewer"]


def test_document_summary_with_explicit_save_requires_write_but_no_coder():
    decision = classify_multiagent_intent(
        "Lee el PDF y guárdame el resumen en un .txt"
    )
    assert decision.intent is MultiAgentIntent.DOCUMENT_SUMMARY
    assert decision.requires_write is True
    # P0: persisting a summary should not pull in the coder/validator phases.
    assert "coder" not in decision.allowed_phases


def test_document_transform_requires_full_flow():
    decision = classify_multiagent_intent("Convertir docx a pdf y exportarlo.")
    assert decision.intent is MultiAgentIntent.DOCUMENT_TRANSFORM
    assert decision.requires_write is True
    assert "coder" in decision.allowed_phases


def test_read_only_answer():
    decision = classify_multiagent_intent("Explícame qué significa esta función, sin editar.")
    assert decision.intent is MultiAgentIntent.READ_ONLY_ANSWER
    assert decision.requires_write is False
    assert "coder" not in decision.allowed_phases


def test_code_change_includes_coder():
    decision = classify_multiagent_intent("implementa un fix en orchestrator.py")
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


def test_spanish_review_only_skips_coder(monkeypatch):
    calls = _run_with_capture(monkeypatch, "Solo analiza, no cambies archivos.")
    assert AgentRole.GENERALIST_CODER not in calls
    assert AgentRole.VALIDATOR not in calls


def test_document_summary_orchestration_skips_coder(monkeypatch):
    calls = _run_with_capture(monkeypatch, "Lee el PDF y resúmelo.")
    assert AgentRole.GENERALIST_CODER not in calls
    assert AgentRole.VALIDATOR not in calls
    assert calls == [AgentRole.RESEARCHER, AgentRole.REVIEWER]


def test_document_summary_with_save_still_skips_coder(monkeypatch):
    calls = _run_with_capture(
        monkeypatch, "Lee el PDF y guárdame el resumen en un .txt"
    )
    assert AgentRole.GENERALIST_CODER not in calls
    assert AgentRole.VALIDATOR not in calls


def test_code_change_orchestration_runs_coder(monkeypatch):
    calls = _run_with_capture(monkeypatch, "implementa un fix en orchestrator.py")
    assert AgentRole.PLANNER in calls
    assert AgentRole.GENERALIST_CODER in calls
    assert AgentRole.VALIDATOR in calls
    assert AgentRole.REVIEWER in calls
