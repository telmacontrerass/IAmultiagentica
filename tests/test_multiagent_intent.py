"""Tests for the deterministic multi-agent intent classifier and its wiring."""

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.multiagent.intent import (
    MultiAgentIntent,
    OrchestrationDecision,
    classify_multiagent_intent,
    classify_orchestration_decision,
    has_dangerous_operation,
    has_explicit_write_intent,
    has_global_no_write,
    has_scope_constraint,
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


# --- P0: write-intent dimension separation (bilingual) --------------------
#
# Core bug: "create X ... do not touch *other* files" is a scoped WRITE task,
# not a global no-write review. The three write-permission dimensions
# (explicit write / scope constraint / global no-write) must stay separate.


def test_dimension_helpers_separate_scope_from_global():
    scoped = "crea un archivo prueba.txt, no modifiques ningún otro archivo"
    assert has_explicit_write_intent(scoped) is True
    assert has_scope_constraint(scoped) is True
    assert has_global_no_write(scoped) is False

    review = "review-only task, do not implement or edit files"
    assert has_explicit_write_intent(review) is False
    assert has_scope_constraint(review) is False
    assert has_global_no_write(review) is True


def test_negated_write_verb_is_not_explicit_write():
    # "do not implement" must not register as a positive write intent.
    assert has_explicit_write_intent("please do not implement or edit anything") is False
    # but a positive verb in an earlier clause still counts.
    assert has_explicit_write_intent("implement this fix, but do not edit other files") is True


def test_p0_spanish_create_with_scope_constraint_is_write_task():
    decision = classify_multiagent_intent(
        "Crea un archivo llamado prueba_multiagente.txt con un saludo. "
        "No modifiques ningún otro archivo."
    )
    assert decision.intent is MultiAgentIntent.CODE_CHANGE
    assert decision.requires_write is True
    assert "coder" in decision.allowed_phases


def test_p0_english_create_with_scope_constraint_is_write_task():
    decision = classify_multiagent_intent(
        "Create a file named test.txt with a greeting. Do not edit anything else."
    )
    assert decision.intent is MultiAgentIntent.CODE_CHANGE
    assert decision.requires_write is True
    assert "coder" in decision.allowed_phases


def test_p0_implement_fix_with_scope_constraint_is_write_task():
    decision = classify_multiagent_intent(
        "Implement this fix, but do not modify unrelated files."
    )
    assert decision.intent is MultiAgentIntent.CODE_CHANGE
    assert decision.requires_write is True
    assert "coder" in decision.allowed_phases


def test_p0_global_no_write_stays_review_only():
    decision = classify_multiagent_intent(
        "Review-only task. Do not implement or edit files."
    )
    assert decision.intent is MultiAgentIntent.REVIEW_ONLY
    assert decision.requires_write is False
    assert "coder" not in decision.allowed_phases


def test_p0_read_and_explain_with_global_no_write_is_not_a_write_task():
    decision = classify_multiagent_intent(
        "Lee este archivo y explícame qué hace. No edites nada."
    )
    assert decision.requires_write is False
    assert "coder" not in decision.allowed_phases
    assert decision.intent in (
        MultiAgentIntent.READ_ONLY_ANSWER,
        MultiAgentIntent.REVIEW_ONLY,
    )


def test_p0_read_pdf_and_save_summary_is_document_summary_with_write():
    decision = classify_multiagent_intent(
        "Lee el PDF y guarda el resumen en resumen_drones.txt."
    )
    assert decision.intent is MultiAgentIntent.DOCUMENT_SUMMARY
    assert decision.requires_write is True
    # Persisting a summary needs a coder to create the output artifact, while the
    # lightweight document flow still skips the validator phase.
    assert "coder" in decision.allowed_phases
    assert "validator" not in decision.allowed_phases


# --- Rich OrchestrationDecision surface -----------------------------------
#
# The new surface separates concerns explicitly: task_type, required
# capabilities, operational risk, allowed phases, and needs_confirmation. It
# never decides final permission — that stays in the execution gate.


def test_orchestration_create_file_is_file_operation_with_write():
    decision = classify_orchestration_decision(
        "Crea un archivo llamado prueba.txt con un saludo. "
        "No modifiques ningún otro archivo."
    )
    assert isinstance(decision, OrchestrationDecision)
    assert decision.task_type == "file_operation"
    assert "write_fs" in decision.required_capabilities
    # Persisting a data file is not a source-code edit.
    assert "edit_code" not in decision.required_capabilities


def test_orchestration_review_only_is_review_with_read_fs():
    decision = classify_orchestration_decision(
        "Revisa el cambio reciente. Review-only, do not edit files."
    )
    assert decision.task_type == "review"
    assert decision.required_capabilities == frozenset({"read_fs"})
    assert "write_fs" not in decision.required_capabilities
    assert decision.needs_confirmation is False


def test_orchestration_implement_fix_is_code_change_with_edit_code():
    decision = classify_orchestration_decision(
        "Implementa un fix en orchestrator.py"
    )
    assert decision.task_type == "code_change"
    assert "edit_code" in decision.required_capabilities
    assert "write_fs" in decision.required_capabilities


def test_orchestration_read_pdf_and_save_is_document_summary():
    decision = classify_orchestration_decision(
        "Lee el PDF y guarda el resumen en resumen_drones.txt."
    )
    assert decision.task_type == "document_summary"
    assert "read_fs" in decision.required_capabilities
    assert "write_fs" in decision.required_capabilities
    assert decision.risk_level == "low"


def test_orchestration_delete_is_dangerous_operation_high_risk():
    decision = classify_orchestration_decision(
        "Borra todos los archivos temporales, limpia el cache y resetea la base."
    )
    assert decision.task_type == "dangerous_operation"
    assert "delete_fs" in decision.required_capabilities
    assert decision.risk_level == "high"
    assert decision.needs_confirmation is True


def test_orchestration_contradictory_prompt_is_ambiguous_needs_confirmation():
    decision = classify_orchestration_decision(
        "Crea un archivo nuevo, pero no escribas nada ni implementes nada."
    )
    assert decision.task_type == "ambiguous"
    assert decision.needs_confirmation is True
    # An unresolved contradiction must not pre-grant write access.
    assert "write_fs" not in decision.required_capabilities


def test_dangerous_operation_respects_negation():
    # A destructive verb inside a negated clause must not flag.
    assert has_dangerous_operation("borra el archivo temporal") is True
    assert has_dangerous_operation("no borres ningún archivo") is False


def test_orchestration_does_not_change_legacy_surface():
    # The legacy decision is unchanged for the same prompt; the rich surface is
    # purely additive.
    prompt = "Implementa un fix en orchestrator.py"
    legacy = classify_multiagent_intent(prompt)
    rich = classify_orchestration_decision(prompt)
    assert legacy.intent is MultiAgentIntent.CODE_CHANGE
    assert tuple(legacy.allowed_phases) == rich.allowed_phases


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
    calls = _run_with_capture(monkeypatch, "implement a fix in orchestrator.py")
    assert AgentRole.PLANNER in calls
    assert AgentRole.GENERALIST_CODER in calls
    assert AgentRole.VALIDATOR in calls
    assert AgentRole.REVIEWER in calls
