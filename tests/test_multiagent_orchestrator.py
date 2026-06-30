import json
from datetime import UTC, datetime

import pytest

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.multiagent.orchestrator import (
    _build_implementation_prompt,
    _build_planner_prompt,
    _build_repair_prompt,
    _build_research_prompt,
    _build_review_prompt,
    _build_security_review_prompt,
    _build_validation_prompt,
    _trace_payload,
    choose_coder_role,
    classify_exact_file_content_contract,
    classify_failure_classification,
    final_run_status,
    has_write_tool_evidence,
    looks_like_untraceable_fs_mutation,
    research_discovered_write_requirement,
    run_multi_agent,
    should_run_security_review,
    should_skip_implementation,
    subagent_blocked,
    synthesize_final_answer,
    validation_failed,
    write_task_lacks_evidence,
)
from ci2lab.harness.multiagent.state import (
    CONTRACT_VALIDATION_SCHEMA_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    FAILURE_CLASSIFICATION_SCHEMA_VERSION,
    AgentRole,
    ContractValidation,
    EvidenceEntry,
    FailureClassification,
    MultiAgentRun,
    SubAgentResult,
)


def _result(role: AgentRole, output: str, *, attempt: int = 1, **kwargs) -> SubAgentResult:
    return SubAgentResult(
        role=role,
        task=f"{role.value} task",
        output=output,
        attempt=attempt,
        **kwargs,
    )


def test_choose_coder_role_prefers_specific_evidence():
    plan = _result(AgentRole.PLANNER, "Update ci2lab/harness/orchestrator.py")
    research = _result(AgentRole.RESEARCHER, "This is Python harness code.")

    assert choose_coder_role(plan, research) == AgentRole.PYTHON_CODER

    plan = _result(AgentRole.PLANNER, "Update ui/static/app.js and styles.css")
    research = _result(AgentRole.RESEARCHER, "Frontend behavior.")

    assert choose_coder_role(plan, research) == AgentRole.FRONTEND_CODER


def test_complete_exercise_does_not_route_to_test_only_coder():
    # Regression: an "implement/complete" task whose evidence merely mentions
    # that unit tests are required must NOT be routed to the test-only coder,
    # which would leave the actual program unwritten. The user prompt has no
    # test request, so it routes to a real implementer.
    plan = _result(AgentRole.PLANNER, "Solve Programa 2 PyRecommender in Python.")
    research = _result(
        AgentRole.RESEARCHER,
        "The program must be developed in Python and include unit tests (pytest).",
    )
    role = choose_coder_role(
        plan,
        research,
        user_prompt="read the exam pdf and complete exercise 2",
    )
    assert role == AgentRole.PYTHON_CODER
    assert role != AgentRole.TEST_CODER


def test_test_centric_user_request_routes_to_test_coder():
    plan = _result(AgentRole.PLANNER, "Add coverage.")
    research = _result(AgentRole.RESEARCHER, "Python module foo.py.")
    assert (
        choose_coder_role(plan, research, user_prompt="write unit tests for foo")
        == AgentRole.TEST_CODER
    )


def test_docs_centric_user_request_routes_to_docs_coder():
    plan = _result(AgentRole.PLANNER, "Edit text.")
    research = _result(AgentRole.RESEARCHER, "Project files.")
    assert (
        choose_coder_role(plan, research, user_prompt="update the README with examples")
        == AgentRole.DOCS_CODER
    )


def test_implementation_request_without_language_signal_uses_generalist():
    plan = _result(AgentRole.PLANNER, "Make the requested change.")
    research = _result(AgentRole.RESEARCHER, "No specific language detected.")
    assert (
        choose_coder_role(plan, research, user_prompt="complete the task")
        == AgentRole.GENERALIST_CODER
    )


def test_should_skip_implementation_for_read_only_pdf_task():
    plan = _result(AgentRole.PLANNER, "Read the PDF and summarize its contents.")
    research = _result(AgentRole.RESEARCHER, "Relevant document: paper.pdf")

    assert should_skip_implementation(
        "read the contents of the pdf and summarize it",
        plan,
        research,
    )


def test_should_not_skip_implementation_for_document_edit_task():
    plan = _result(AgentRole.PLANNER, "Update README.md")
    research = _result(AgentRole.RESEARCHER, "Relevant document: README.md")

    assert not should_skip_implementation(
        "update the README with a new example",
        plan,
        research,
    )


def test_validation_failed_detects_failure_and_pass():
    assert validation_failed(_result(AgentRole.VALIDATOR, "pytest failed"))
    assert not validation_failed(_result(AgentRole.VALIDATOR, "pytest passed"))
    assert not validation_failed(_result(AgentRole.VALIDATOR, "no errors"))


def test_subagent_blocked_detects_explicit_and_round_limit_blocks():
    assert subagent_blocked(_result(AgentRole.RESEARCHER, "BLOCKED: missing file"))
    assert subagent_blocked(
        _result(AgentRole.RESEARCHER, "Reached the max rounds limit without a final answer.")
    )
    assert not subagent_blocked(_result(AgentRole.RESEARCHER, "Found the context."))


def test_planner_prompt_requires_role_assignments_dependencies_and_boundaries():
    prompt = _build_planner_prompt("Add a feature")

    assert "authoritative execution plan" in prompt
    assert "Role assignments" in prompt
    assert "Dependencies" in prompt
    assert "Boundaries" in prompt
    assert "non-overlapping" in prompt


def test_downstream_prompts_require_following_planner_contract():
    plan = _result(
        AgentRole.PLANNER,
        "Role assignments: researcher reads files; python_coder edits app.py.\n"
        "Dependencies: coder uses researcher findings.\n"
        "Boundaries: reviewer does not edit files.",
    )
    research = _result(AgentRole.RESEARCHER, "Relevant file: app.py")
    implementation = _result(AgentRole.PYTHON_CODER, "Changed app.py")

    research_prompt = _build_research_prompt("Add a feature", plan)
    implementation_prompt = _build_implementation_prompt("Add a feature", plan, research)
    validation_prompt = _build_validation_prompt(
        "Add a feature",
        plan,
        research,
        implementation,
    )
    from ci2lab.harness.multiagent.state import MultiAgentRun

    run = MultiAgentRun(user_prompt="Add a feature")
    run.add_result(plan)
    run.add_result(research)
    run.add_result(implementation)
    review_prompt = _build_review_prompt(run)

    assert "Follow the planner's execution plan" in research_prompt
    assert "Only perform the research/context gathering assigned" in research_prompt
    assert "Implement only the tasks assigned" in implementation_prompt
    # Wording is plan-source-agnostic: a document task runs no planner.
    assert "outside the stated boundaries" in implementation_prompt
    assert "planner's validation expectations" in validation_prompt
    assert "did not follow the plan" in validation_prompt
    assert "against the planner's execution plan" in review_prompt
    assert "avoided overlapping responsibilities" in review_prompt


def test_validator_prompt_requires_real_tool_evidence_for_claims():
    plan = _result(AgentRole.PLANNER, "Create prueba_multiagente.txt.")
    research = _result(AgentRole.RESEARCHER, "No existing target file found.")
    implementation = _result(
        AgentRole.GENERALIST_CODER,
        "I created prueba_multiagente.txt and checked the content.",
        tool_calls=[],
    )

    prompt = _build_validation_prompt(
        "Create prueba_multiagente.txt with MULTIAGENTE_OK.",
        plan,
        research,
        implementation,
    )

    assert "Real tool-call evidence available" in prompt
    assert "Filesystem write evidence:\nnone" in prompt
    assert "Readback/content evidence:\nnone" in prompt
    assert "insufficient evidence" in prompt
    assert "non-existent verification helpers" in prompt
    assert "verificar_archivo" not in prompt
    assert "check_content" not in prompt


def test_validator_prompt_records_successful_write_and_readback_evidence():
    plan = _result(AgentRole.PLANNER, "Create prueba_multiagente.txt.")
    research = _result(AgentRole.RESEARCHER, "No existing target file found.")
    implementation = _result(
        AgentRole.GENERALIST_CODER,
        "Implemented requested file.",
        tool_calls=[
            {
                "tool": "write_file",
                "ok": True,
                "arguments": {"path": "prueba_multiagente.txt"},
                "output_preview": "Wrote prueba_multiagente.txt",
            },
            {
                "tool": "read_file",
                "ok": True,
                "arguments": {"path": "prueba_multiagente.txt"},
                "output_preview": "MULTIAGENTE_OK",
            },
        ],
    )

    prompt = _build_validation_prompt(
        "Create prueba_multiagente.txt with MULTIAGENTE_OK.",
        plan,
        research,
        implementation,
    )

    assert "generalist_coder: write_file(prueba_multiagente.txt)" in prompt
    assert "generalist_coder: read_file(prueba_multiagente.txt)" in prompt
    assert "MULTIAGENTE_OK" in prompt


def test_reviewer_prompt_does_not_allow_creation_claim_without_implementer():
    from ci2lab.harness.multiagent.state import MultiAgentRun

    run = MultiAgentRun(user_prompt="Read the PDF and summarize it.")
    run.add_result(_result(AgentRole.RESEARCHER, "Found the PDF summary."))

    prompt = _build_review_prompt(run)

    assert "Selected implementer: none selected" in prompt
    assert "Filesystem write evidence:\nnone" in prompt
    assert "You may say a file was created or modified only" in prompt
    assert "insufficient evidence" in prompt


def test_security_reviewer_prompt_does_not_allow_filesystem_write_claim_without_tool_result():
    from ci2lab.harness.multiagent.state import MultiAgentRun

    run = MultiAgentRun(user_prompt="Review filesystem safety.")
    run.add_result(_result(AgentRole.RESEARCHER, "No writes needed."))
    run.add_result(_result(AgentRole.REVIEWER, "Looks safe."))

    prompt = _build_security_review_prompt(run)

    assert "Selected implementer: none selected" in prompt
    assert "Filesystem write evidence:\nnone" in prompt
    assert "do not state that an implementer created, modified, or wrote files" in prompt
    assert "insufficient evidence of filesystem writes" in prompt


def test_should_run_security_review_for_sensitive_terms():
    from ci2lab.harness.multiagent.state import MultiAgentRun

    run = MultiAgentRun(user_prompt="Change permission handling")
    run.add_result(_result(AgentRole.PYTHON_CODER, "Updated approval rules"))

    assert should_run_security_review(run)


def test_run_multi_agent_sequential_flow(monkeypatch):
    calls: list[tuple[AgentRole, int]] = []
    selections = []
    outputs = {
        AgentRole.PLANNER: "Plan: edit ci2lab/harness/example.py",
        AgentRole.RESEARCHER: "Relevant Python file: ci2lab/harness/example.py",
        AgentRole.PYTHON_CODER: "Implemented Python change.",
        AgentRole.VALIDATOR: "pytest passed",
        AgentRole.REVIEWER: "No issues found.",
    }

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append((role, attempt))
        selections.append(selection)
        return _result(role, outputs[role], attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    selected = default_selection("user-selected:7b")
    result = run_multi_agent(
        "Make a Python change",
        selected,
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert calls == [
        (AgentRole.PLANNER, 1),
        (AgentRole.RESEARCHER, 1),
        (AgentRole.PYTHON_CODER, 1),
        (AgentRole.VALIDATOR, 1),
        (AgentRole.REVIEWER, 1),
    ]
    assert selections == [selected] * len(calls)
    assert "Selected implementer: python_coder" in result
    assert "pytest passed" in result


def test_run_multi_agent_skips_coder_for_read_only_pdf_task(monkeypatch):
    calls: list[tuple[AgentRole, int]] = []
    outputs = {
        AgentRole.PLANNER: "Plan: read the PDF and answer from its content.",
        AgentRole.RESEARCHER: "The PDF content says the main topic is formal writing.",
        AgentRole.REVIEWER: "The answer is grounded in the document. No code needed.",
    }

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append((role, attempt))
        return _result(role, outputs[role], attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        "access the contents of the pdf test.pdf and tell me what it is about",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert calls == [
        (AgentRole.PLANNER, 1),
        (AgentRole.RESEARCHER, 1),
        (AgentRole.REVIEWER, 1),
    ]
    assert "Selected implementer: none (read-only task)" in result
    assert "formal writing" in result


def test_research_discovered_pdf_exercise_promotes_to_write_flow(monkeypatch):
    calls: list[tuple[AgentRole, int]] = []
    outputs = {
        AgentRole.PLANNER: (
            "Plan: read the PDF, identify Exercise 2, then perform_exercise_2: "
            "Carry out the task specified in Exercise 2."
        ),
        AgentRole.RESEARCHER: (
            "Exercise 2 is called Problema de programacion. The task involves "
            "implementing a program in Python. Constraints: no use of the `in` "
            "operator; only use of the append method for lists."
        ),
        AgentRole.PYTHON_CODER: "Implemented Exercise 2 in Python.",
        AgentRole.VALIDATOR: "PASS: implementation satisfies the exercise.",
        AgentRole.REVIEWER: "PASS: evidence confirms the task was completed.",
    }

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append((role, attempt))
        return _result(role, outputs[role], attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        "read '2025-26.-Examen Diciembre Programación iMAT.pdf' and follow "
        "the instructions to do exercise 2 (called differently inside the document)",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert calls == [
        (AgentRole.PLANNER, 1),
        (AgentRole.RESEARCHER, 1),
        (AgentRole.PYTHON_CODER, 1),
        (AgentRole.VALIDATOR, 1),
        (AgentRole.REVIEWER, 1),
    ]
    assert "Selected implementer: python_coder" in result
    assert "Selected implementer: none" not in result


def test_research_discovered_write_requirement_from_code_constraints():
    plan = _result(AgentRole.PLANNER, "Plan: read PDF and perform exercise 2.")
    research = _result(
        AgentRole.RESEARCHER,
        "The task involves implementing a program in Python. No use of the `in` "
        "operator. Only use append for lists.",
    )

    assert research_discovered_write_requirement(
        "read exam.pdf and follow the instructions to do exercise 2",
        plan,
        research,
    )


def test_reviewer_insufficient_evidence_blocks_completed_status():
    run = MultiAgentRun(user_prompt="Implement the requested exercise.")
    run.requires_write = True
    run.selected_coder_role = AgentRole.PYTHON_CODER
    run.add_result(
        _result(
            AgentRole.PYTHON_CODER,
            "Implemented.",
            tool_calls=[
                {
                    "tool": "write_file",
                    "ok": True,
                    "arguments": {"path": "exercise.py"},
                    "output_preview": "wrote",
                }
            ],
        )
    )
    run.add_result(
        _result(
            AgentRole.REVIEWER,
            "However, there is insufficient evidence to confirm if the task "
            "specified in Exercise 2 was completed.",
        )
    )

    assert final_run_status(run) == "review_failed"


def test_security_fail_blocks_completed_status_and_final_answer():
    run = MultiAgentRun(user_prompt="Implement the requested exercise.")
    run.requires_write = True
    run.selected_coder_role = AgentRole.PYTHON_CODER
    run.add_result(
        _result(
            AgentRole.PYTHON_CODER,
            "Implemented.",
            tool_calls=[
                {
                    "tool": "write_file",
                    "ok": True,
                    "arguments": {"path": "exercise.py"},
                    "output_preview": "wrote",
                }
            ],
        )
    )
    run.add_result(
        _result(
            AgentRole.SECURITY_REVIEWER,
            "FAIL: unresolved security/permission evidence gaps: git_status, git_diff",
        )
    )

    assert final_run_status(run) == "security_failed"
    assert "status: completed" not in synthesize_final_answer(run)


def test_write_required_without_implementer_is_not_completed():
    run = MultiAgentRun(user_prompt="Implement exercise 2 from the PDF.")
    run.requires_write = True
    run.add_result(_result(AgentRole.RESEARCHER, "The task involves implementing Python."))

    final = synthesize_final_answer(run)

    assert "status: implementation_required_but_not_executed" in final
    assert "Selected implementer: none (implementation required but not executed)" in final


def test_run_multi_agent_stops_when_researcher_is_blocked(monkeypatch):
    calls: list[AgentRole] = []

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append(role)
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: inspect the requested PDF.")
        if role == AgentRole.RESEARCHER:
            return _result(role, "BLOCKED: test.pdf was not found.")
        raise AssertionError(f"Unexpected role after blocked researcher: {role}")

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        "access the contents of the pdf test.pdf and tell me what it is about",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert calls == [AgentRole.PLANNER, AgentRole.RESEARCHER]
    assert "status: blocked" in result
    assert "Blocked role: researcher" in result
    assert "test.pdf was not found" in result


def test_blocked_validator_does_not_abort_run(monkeypatch):
    # Regression: a confused validator that replies "BLOCKED: please provide a
    # validation step" must not discard the coder's work. The reviewer still
    # runs and the run finishes completed, not blocked.
    calls: list[AgentRole] = []
    outputs = {
        AgentRole.PLANNER: "Plan: edit ci2lab/harness/example.py",
        AgentRole.RESEARCHER: "Relevant Python file: ci2lab/harness/example.py",
        AgentRole.PYTHON_CODER: "Implemented Python change.",
        AgentRole.VALIDATOR: "BLOCKED: please provide a validation step.",
        AgentRole.REVIEWER: "Implementation looks correct.",
    }

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append(role)
        return _result(role, outputs[role], attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        "complete exercise 2 in Python",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert AgentRole.REVIEWER in calls  # reviewer was not skipped
    assert "status: blocked" not in result
    assert "Blocked role: validator" not in result
    assert "Implementation looks correct." in result


def test_run_multi_agent_prints_subagent_progress(monkeypatch):
    outputs = {
        AgentRole.PLANNER: "Plan: edit ci2lab/harness/example.py",
        AgentRole.RESEARCHER: "Relevant Python file: ci2lab/harness/example.py",
        AgentRole.PYTHON_CODER: "Implemented Python change.",
        AgentRole.VALIDATOR: "pytest passed",
        AgentRole.REVIEWER: "No issues found.",
    }
    printed: list[str] = []

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        return _result(role, outputs[role], attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )
    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.console.print",
        lambda message: printed.append(str(message)),
    )

    run_multi_agent(
        "Make a Python change",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert any("Planning the work" in message for message in printed)
    assert any("completed planner" in message for message in printed)
    assert any("Gathering the needed context" in message for message in printed)
    assert any("completed python_coder" in message for message in printed)
    assert any("Checking the result" in message for message in printed)
    assert any("completed reviewer" in message for message in printed)


def test_all_multiagent_role_progress_labels_are_english():
    from ci2lab.harness.multiagent.orchestrator import _role_progress_label

    expected = {
        AgentRole.PLANNER: "Planning the work",
        AgentRole.RESEARCHER: "Gathering the needed context",
        AgentRole.PYTHON_CODER: "Applying Python changes",
        AgentRole.FRONTEND_CODER: "Applying interface changes",
        AgentRole.TEST_CODER: "Updating tests",
        AgentRole.DOCS_CODER: "Updating documentation",
        AgentRole.GENERALIST_CODER: "Applying the requested changes",
        AgentRole.VALIDATOR: "Checking the result",
        AgentRole.REVIEWER: "Reviewing the outcome",
        AgentRole.SECURITY_REVIEWER: "Reviewing security and permissions",
        AgentRole.INTAKE_REVIEWER: "Diagnosing the manuscript",
        AgentRole.SCOPE_REVIEWER: "Checking journal fit",
        AgentRole.NOVELTY_REVIEWER: "Auditing the contribution",
        AgentRole.METHODOLOGY_REVIEWER: "Reviewing the methodology",
        AgentRole.FIELD_EXPERT_REVIEWER: "Applying field expectations",
        AgentRole.ADVERSARIAL_REVIEWER: "Mounting Reviewer 2 objections",
        AgentRole.FORMAT_REVIEWER: "Checking submission readiness",
        AgentRole.GROUNDEDNESS_VERIFIER: "Verifying findings against the paper",
        AgentRole.REVISION_PLANNER: "Assembling the review report",
    }

    assert {role: _role_progress_label(role, 1) for role in AgentRole} == expected


def test_run_multi_agent_repairs_with_same_coder(monkeypatch):
    calls: list[tuple[AgentRole, int]] = []
    validator_outputs = iter(["pytest failed: assertion error", "pytest passed"])

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append((role, attempt))
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: edit ci2lab/harness/example.py")
        if role == AgentRole.RESEARCHER:
            return _result(role, "Relevant Python file: ci2lab/harness/example.py")
        if role == AgentRole.PYTHON_CODER:
            return _result(role, f"Python change attempt {attempt}", attempt=attempt)
        if role == AgentRole.VALIDATOR:
            return _result(role, next(validator_outputs), attempt=attempt)
        return _result(role, "Review complete", attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        "Make a Python change",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
        max_repair_attempts=2,
    )

    assert calls == [
        (AgentRole.PLANNER, 1),
        (AgentRole.RESEARCHER, 1),
        (AgentRole.PYTHON_CODER, 1),
        (AgentRole.VALIDATOR, 1),
        (AgentRole.PYTHON_CODER, 2),
        (AgentRole.VALIDATOR, 2),
        (AgentRole.REVIEWER, 1),
    ]
    assert "Selected implementer: python_coder" in result
    assert "pytest passed" in result


def test_run_multi_agent_adds_security_review_when_needed(monkeypatch):
    calls: list[tuple[AgentRole, int]] = []

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        calls.append((role, attempt))
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: update permission code in ci2lab/security")
        if role == AgentRole.RESEARCHER:
            return _result(role, "Security-sensitive approval behavior")
        if role == AgentRole.PYTHON_CODER:
            return _result(role, "Implemented permission change")
        if role == AgentRole.VALIDATOR:
            return _result(role, "pytest passed")
        if role == AgentRole.SECURITY_REVIEWER:
            return _result(role, "Security review passed")
        return _result(role, "Review complete")

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        "Change permission handling",
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
    )

    assert calls[-2:] == [
        (AgentRole.REVIEWER, 1),
        (AgentRole.SECURITY_REVIEWER, 1),
    ]
    assert "Security review passed" in result


def test_multiagent_trace_records_phase_sequence(tmp_path, monkeypatch):
    outputs = {
        AgentRole.PLANNER: "Plan output",
        AgentRole.RESEARCHER: "Research output",
        AgentRole.PYTHON_CODER: "Implemented output",
        AgentRole.VALIDATOR: "pytest passed",
        AgentRole.REVIEWER: "Review output",
    }

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        return _result(
            role,
            outputs.get(role, "Generic output"),
            attempt=attempt,
            role_anchor=f"Role anchor: {role.value}",
            allowed_tools=["read_file"],
            input_prompt=task_prompt,
            rounds=1,
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    cfg = AgentConfig(
        cwd=str(tmp_path),
        runs_dir=str(tmp_path / "runs"),
        run_log_enabled=True,
    )
    run_multi_agent("Make a Python change", default_selection("test:1b"), config=cfg)

    run_dirs = sorted((tmp_path / "runs").iterdir())
    trace = json.loads((run_dirs[0] / "multiagent_trace.json").read_text(encoding="utf-8"))
    assert trace["planned_phases"][:2] == ["planner", "researcher"]
    # "Make a Python change" routes to the Python implementer.
    assert trace["selected_coder_role"] == "python_coder"
    assert trace["executed_phases"][:5] == [
        "planner",
        "researcher",
        "python_coder",
        "validator",
        "reviewer",
    ]
    assert (run_dirs[0] / "multiagent_trace.json").is_file()


def test_evidence_entry_can_be_built_from_existing_tool_call_shape():
    entry = EvidenceEntry.from_tool_call(
        {
            "tool": "write_file",
            "ok": True,
            "outcome": "approved",
            "arguments": {"path": "notes/todo.txt", "content": "TODO_OK"},
            "output_preview": "Wrote notes/todo.txt",
            "error_preview": None,
        },
        role=AgentRole.GENERALIST_CODER,
        source_run="runs/child",
    )

    data = entry.to_dict()
    assert data["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert data["role"] == "generalist_coder"
    assert data["phase"] == "generalist_coder"
    assert data["tool"] == "write_file"
    assert data["ok"] is True
    assert data["args"] == {"path": "notes/todo.txt", "content": "TODO_OK"}
    assert data["target_path"] == "notes/todo.txt"
    assert data["output_preview"] == "Wrote notes/todo.txt"
    assert data["output_hash"]
    assert data["source_run"] == "runs/child"
    assert data["failure_class"] is None


def test_contract_validation_serializes_stable_schema():
    contract_validation = ContractValidation(
        kind="file_content",
        status="not_evaluated",
        expected_artifacts=[{"path": "notes/todo.txt"}],
        observed_artifacts=[],
        required_evidence=["write_file", "read_file"],
        observed_evidence=["write_file"],
        missing_evidence=["read_file"],
        failures=[],
        notes=["advisory trace only"],
    )

    data = contract_validation.to_dict()
    assert data["schema_version"] == CONTRACT_VALIDATION_SCHEMA_VERSION
    assert data["kind"] == "file_content"
    assert data["status"] == "not_evaluated"
    assert data["expected_artifacts"] == [{"path": "notes/todo.txt"}]
    assert data["observed_artifacts"] == []
    assert data["required_evidence"] == ["write_file", "read_file"]
    assert data["observed_evidence"] == ["write_file"]
    assert data["missing_evidence"] == ["read_file"]
    assert data["failures"] == []
    assert data["notes"] == ["advisory trace only"]
    assert data["allowed_write_paths"] == []
    assert data["allowed_write_roots"] == []
    assert data["observed_changed_paths"] == []
    assert data["scope_status"] is None
    assert data["scope_failures"] == []
    json.dumps(data)


def test_failure_classification_serializes_stable_schema():
    failure = FailureClassification(
        status="tool_trace_failed",
        failure_class="missing_write_evidence",
        failure_reason="missing required evidence: write_file",
        failed_phase="generalist_coder",
        repairable=False,
        related_evidence=["read_file", "write_file"],
        contract_kind="exact_file_content",
        details={"missing_evidence": ["write_file"]},
    )

    data = failure.to_dict()
    assert data["schema_version"] == FAILURE_CLASSIFICATION_SCHEMA_VERSION
    assert data["status"] == "tool_trace_failed"
    assert data["failure_class"] == "missing_write_evidence"
    assert data["failed_phase"] == "generalist_coder"
    assert data["repairable"] is False
    assert data["related_evidence"] == ["read_file", "write_file"]
    assert data["contract_kind"] == "exact_file_content"
    assert data["details"] == {"missing_evidence": ["write_file"]}
    json.dumps(data)


def _exact_contract_run(tmp_path, *, prompt: str | None = None) -> MultiAgentRun:
    run = MultiAgentRun(
        user_prompt=prompt
        or "Create a file named notes/todo.txt with exactly this content: TODO_OK."
    )
    run.requires_write = True
    run.selected_coder_role = AgentRole.GENERALIST_CODER
    return run


def _exact_contract_with_evidence(
    tmp_path,
    *,
    prompt: str,
    status_output: str,
    target_path: str = "notes/todo.txt",
) -> MultiAgentRun:
    target = tmp_path / target_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("TODO_OK", encoding="utf-8")
    run = _exact_contract_run(tmp_path, prompt=prompt)
    run.add_result(
        _result(
            AgentRole.GENERALIST_CODER,
            "Done.",
            tool_calls=[
                {
                    "tool": "write_file",
                    "ok": True,
                    "arguments": {"path": target_path, "content": "TODO_OK"},
                    "output_preview": f"Wrote {target_path}",
                },
                {
                    "tool": "read_file",
                    "ok": True,
                    "arguments": {"path": target_path},
                    "output_preview": "TODO_OK",
                },
                {
                    "tool": "git_status",
                    "ok": True,
                    "arguments": {"path": "."},
                    "output_preview": status_output,
                },
            ],
        )
    )
    return run


def test_exact_file_contract_completed_with_write_and_readback_evidence(tmp_path):
    target = tmp_path / "notes" / "todo.txt"
    target.parent.mkdir()
    target.write_text("TODO_OK", encoding="utf-8")
    run = _exact_contract_run(tmp_path)
    run.add_result(
        _result(
            AgentRole.GENERALIST_CODER,
            "Done.",
            tool_calls=[
                {
                    "tool": "write_file",
                    "ok": True,
                    "arguments": {"path": "notes/todo.txt", "content": "TODO_OK"},
                    "output_preview": "Wrote notes/todo.txt",
                },
                {
                    "tool": "read_file",
                    "ok": True,
                    "arguments": {"path": "notes/todo.txt"},
                    "output_preview": "TODO_OK",
                },
            ],
        )
    )

    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )

    assert run.contract_validation is not None
    data = run.contract_validation.to_dict()
    assert data["kind"] == "exact_file_content"
    assert data["status"] == "completed"
    assert data["expected_artifacts"][0]["path"] == "notes/todo.txt"
    assert data["observed_artifacts"][0]["content_matches"] is True
    assert data["required_evidence"] == ["write_file", "read_file"]
    assert data["observed_evidence"] == ["write_file", "read_file"]
    assert data["missing_evidence"] == []
    run.failure_classification = classify_failure_classification(run)
    assert run.failure_classification is None
    assert final_run_status(run) == "completed"


def test_exact_file_contract_scope_expected_file_only_is_completed(tmp_path):
    run = _exact_contract_with_evidence(
        tmp_path,
        prompt=(
            "Create a file named notes/todo.txt with exactly this content: TODO_OK. "
            "Do not modify any other file."
        ),
        status_output="?? notes/todo.txt\n",
    )

    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )
    run.failure_classification = classify_failure_classification(run)

    assert run.contract_validation is not None
    assert run.contract_validation.status == "completed"
    assert run.contract_validation.allowed_write_paths == ["notes/todo.txt"]
    assert run.contract_validation.observed_changed_paths == ["notes/todo.txt"]
    assert run.contract_validation.scope_status == "passed"
    assert run.failure_classification is None
    assert final_run_status(run) == "completed"


def test_exact_file_contract_scope_extra_file_is_scope_violation(tmp_path):
    run = _exact_contract_with_evidence(
        tmp_path,
        prompt=(
            "Create a file named notes/todo.txt with exactly this content: TODO_OK. "
            "Do not modify any other file."
        ),
        status_output="?? notes/todo.txt\n M app.py\n",
    )

    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )
    run.failure_classification = classify_failure_classification(run)

    assert run.contract_validation is not None
    assert run.contract_validation.status == "validation_failed"
    assert run.contract_validation.scope_status == "failed"
    assert run.contract_validation.scope_failures == [
        "changed path outside allowed scope: app.py"
    ]
    assert run.failure_classification is not None
    assert run.failure_classification.failure_class == "scope_violation"
    assert final_run_status(run) == "validation_failed"


def test_exact_file_contract_without_scope_phrase_does_not_enforce_extra_file(tmp_path):
    run = _exact_contract_with_evidence(
        tmp_path,
        prompt="Create a file named notes/todo.txt with exactly this content: TODO_OK.",
        status_output="?? notes/todo.txt\n M app.py\n",
    )

    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )

    assert run.contract_validation is not None
    assert run.contract_validation.status == "completed"
    assert run.contract_validation.allowed_write_paths == []
    assert run.contract_validation.allowed_write_roots == []
    assert run.contract_validation.scope_status is None


def test_ambiguous_prompt_does_not_activate_scope_contract(tmp_path):
    run = _exact_contract_run(tmp_path, prompt="Update the project as needed.")

    contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )

    assert contract_validation is None


def test_exact_file_contract_folder_scope_allows_inside_folder(tmp_path):
    run = _exact_contract_with_evidence(
        tmp_path,
        prompt=(
            "Create a file named exercise_1/result.txt with exactly this content: "
            "TODO_OK. Work only inside folder exercise_1."
        ),
        target_path="exercise_1/result.txt",
        status_output="?? exercise_1/result.txt\n?? exercise_1/notes.txt\n",
    )

    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )

    assert run.contract_validation is not None
    assert run.contract_validation.status == "completed"
    assert run.contract_validation.allowed_write_roots == ["exercise_1/"]
    assert run.contract_validation.scope_status == "passed"


def test_exact_file_contract_folder_scope_rejects_outside_folder(tmp_path):
    run = _exact_contract_with_evidence(
        tmp_path,
        prompt=(
            "Create a file named exercise_1/result.txt with exactly this content: "
            "TODO_OK. Work only inside folder exercise_1."
        ),
        target_path="exercise_1/result.txt",
        status_output="?? exercise_1/result.txt\n?? outside.txt\n",
    )

    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )
    run.failure_classification = classify_failure_classification(run)

    assert run.contract_validation is not None
    assert run.contract_validation.status == "validation_failed"
    assert run.contract_validation.scope_status == "failed"
    assert run.failure_classification is not None
    assert run.failure_classification.failure_class == "scope_violation"


def test_trace_serializes_scope_contract_and_failure_classification(tmp_path):
    run = _exact_contract_with_evidence(
        tmp_path,
        prompt=(
            "Create a file named notes/todo.txt with exactly this content: TODO_OK. "
            "Do not modify any other file."
        ),
        status_output="?? notes/todo.txt\n?? outside.txt\n",
    )
    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )
    run.failure_classification = classify_failure_classification(run)
    started = datetime(2026, 6, 30, tzinfo=UTC)

    trace = _trace_payload(
        run,
        default_selection("test:1b"),
        AgentConfig(cwd=str(tmp_path)),
        started_at=started,
        ended_at=started,
    )

    assert trace["status"] == "validation_failed"
    assert trace["contract_validation"]["allowed_write_paths"] == ["notes/todo.txt"]
    assert trace["contract_validation"]["observed_changed_paths"] == [
        "notes/todo.txt",
        "outside.txt",
    ]
    assert trace["contract_validation"]["scope_status"] == "failed"
    assert trace["failure_classification"]["failure_class"] == "scope_violation"
    coder_phase = next(phase for phase in trace["phases"] if phase["role"] == "generalist_coder")
    assert coder_phase["tool_calls"]
    assert coder_phase["evidence_entries"]


def test_exact_file_contract_correct_file_without_write_evidence_is_tool_trace_failed(
    tmp_path,
):
    target = tmp_path / "notes" / "todo.txt"
    target.parent.mkdir()
    target.write_text("TODO_OK", encoding="utf-8")
    run = _exact_contract_run(tmp_path)
    run.add_result(
        _result(
            AgentRole.GENERALIST_CODER,
            "Done.",
            tool_calls=[
                {
                    "tool": "read_file",
                    "ok": True,
                    "arguments": {"path": "notes/todo.txt"},
                    "output_preview": "TODO_OK",
                }
            ],
        )
    )

    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )

    assert run.contract_validation is not None
    assert run.contract_validation.status == "tool_trace_failed"
    assert run.contract_validation.missing_evidence == ["write_file"]
    run.failure_classification = classify_failure_classification(run)
    assert run.failure_classification is not None
    assert run.failure_classification.failure_class == "missing_write_evidence"
    assert final_run_status(run) == "tool_trace_failed"


def test_exact_file_contract_wrong_content_is_validation_failed(tmp_path):
    target = tmp_path / "notes" / "todo.txt"
    target.parent.mkdir()
    target.write_text("TODO_BAD", encoding="utf-8")
    run = _exact_contract_run(tmp_path)
    run.add_result(
        _result(
            AgentRole.GENERALIST_CODER,
            "Done.",
            tool_calls=[
                {
                    "tool": "write_file",
                    "ok": True,
                    "arguments": {"path": "notes/todo.txt", "content": "TODO_BAD"},
                    "output_preview": "Wrote notes/todo.txt",
                },
                {
                    "tool": "read_file",
                    "ok": True,
                    "arguments": {"path": "notes/todo.txt"},
                    "output_preview": "TODO_BAD",
                },
            ],
        )
    )

    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )

    assert run.contract_validation is not None
    assert run.contract_validation.status == "validation_failed"
    assert "expected artifact content does not match" in run.contract_validation.failures
    run.failure_classification = classify_failure_classification(run)
    assert run.failure_classification is not None
    assert run.failure_classification.failure_class == "content_mismatch"
    assert final_run_status(run) == "validation_failed"


def test_exact_file_contract_missing_readback_is_tool_trace_failed(tmp_path):
    target = tmp_path / "notes" / "todo.txt"
    target.parent.mkdir()
    target.write_text("TODO_OK", encoding="utf-8")
    run = _exact_contract_run(tmp_path)
    run.add_result(
        _result(
            AgentRole.GENERALIST_CODER,
            "Done.",
            tool_calls=[
                {
                    "tool": "write_file",
                    "ok": True,
                    "arguments": {"path": "notes/todo.txt", "content": "TODO_OK"},
                    "output_preview": "Wrote notes/todo.txt",
                }
            ],
        )
    )

    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )

    assert run.contract_validation is not None
    assert run.contract_validation.status == "tool_trace_failed"
    assert run.contract_validation.missing_evidence == ["read_file"]
    run.failure_classification = classify_failure_classification(run)
    assert run.failure_classification is not None
    assert run.failure_classification.failure_class == "missing_readback_evidence"
    assert final_run_status(run) == "tool_trace_failed"


def test_exact_file_contract_missing_file_is_missing_artifact(tmp_path):
    run = _exact_contract_run(tmp_path)
    run.add_result(
        _result(
            AgentRole.GENERALIST_CODER,
            "Done.",
            tool_calls=[
                {
                    "tool": "write_file",
                    "ok": True,
                    "arguments": {"path": "notes/todo.txt", "content": "TODO_OK"},
                    "output_preview": "Wrote notes/todo.txt",
                },
                {
                    "tool": "read_file",
                    "ok": True,
                    "arguments": {"path": "notes/todo.txt"},
                    "output_preview": "TODO_OK",
                },
            ],
        )
    )

    run.contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )
    run.failure_classification = classify_failure_classification(run)

    assert run.contract_validation is not None
    assert run.contract_validation.status == "insufficient_evidence"
    assert run.failure_classification is not None
    assert run.failure_classification.failure_class == "missing_artifact"
    assert final_run_status(run) == "insufficient_evidence"


def test_non_exact_file_prompt_does_not_activate_contract_validation(tmp_path):
    run = _exact_contract_run(
        tmp_path,
        prompt="Create notes/todo.txt with content TODO_OK.",
    )

    contract_validation = classify_exact_file_content_contract(
        run,
        AgentConfig(cwd=str(tmp_path)),
    )

    assert contract_validation is None


def test_failure_classification_maps_existing_phase_failures():
    validator_run = MultiAgentRun(user_prompt="Implement feature")
    validator_run.add_result(_result(AgentRole.VALIDATOR, "pytest failed"))
    validator_failure = classify_failure_classification(validator_run)
    assert validator_failure is not None
    assert validator_failure.failure_class == "validator_failed"
    assert validator_failure.failed_phase == "validator"

    reviewer_run = MultiAgentRun(user_prompt="Implement feature")
    reviewer_run.add_result(_result(AgentRole.REVIEWER, "Insufficient evidence."))
    reviewer_failure = classify_failure_classification(reviewer_run)
    assert reviewer_failure is not None
    assert reviewer_failure.failure_class == "review_failed"
    assert reviewer_failure.failed_phase == "reviewer"

    security_run = MultiAgentRun(user_prompt="Implement feature")
    security_run.add_result(
        _result(
            AgentRole.SECURITY_REVIEWER,
            "FAIL: unresolved security/permission evidence gaps.",
        )
    )
    security_failure = classify_failure_classification(security_run)
    assert security_failure is not None
    assert security_failure.failure_class == "security_failed"
    assert security_failure.failed_phase == "security_reviewer"


def test_failure_classification_maps_role_violation():
    run = MultiAgentRun(user_prompt="Validate feature")
    violation = _result(AgentRole.VALIDATOR, "I tried todo_write.")
    violation.status = "role_violation"
    violation.error = "role_violation: validator attempted forbidden tool(s): todo_write"
    run.add_result(violation)

    failure = classify_failure_classification(run)

    assert failure is not None
    assert failure.failure_class == "role_violation"
    assert failure.failed_phase == "validator"


def test_multiagent_parent_run_persists_workflow_artifacts(tmp_path, monkeypatch):
    child_counter = 0

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        nonlocal child_counter
        child_counter += 1
        child_dir = tmp_path / "runs" / f"child_{child_counter:02d}_{role.value}"
        child_dir.mkdir(parents=True)
        (child_dir / "run_summary.json").write_text(
            json.dumps(
                {
                    "started_at": f"2026-06-26T00:00:0{child_counter}+00:00",
                    "ended_at": f"2026-06-26T00:00:1{child_counter}+00:00",
                    "model": selection.ollama_tag,
                }
            ),
            encoding="utf-8",
        )
        (child_dir / "tool_calls.jsonl").write_text("", encoding="utf-8")
        return _result(
            role,
            "pytest passed" if role == AgentRole.VALIDATOR else f"{role.value} output",
            attempt=attempt,
            subagent_run_dir=str(child_dir),
            tool_calls=[
                {
                    # The implementer (whichever coder role the router selects)
                    # records real write evidence; other roles only read.
                    "tool": "write_file" if "coder" in role.value else "read_file",
                    "ok": True,
                    "arguments": {"path": "x.py"},
                    "output_preview": "ok",
                }
            ],
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    final = run_multi_agent(
        "Make a Python change",
        default_selection("test:1b"),
        config=AgentConfig(
            cwd=str(tmp_path),
            runs_dir=str(tmp_path / "runs"),
            run_log_enabled=True,
        ),
    )

    parent_dirs = sorted((tmp_path / "runs").glob("*/run.json"))
    assert parent_dirs, "parent run.json was not created"
    parent_dir = parent_dirs[0].parent
    run_json = json.loads((parent_dir / "run.json").read_text(encoding="utf-8"))
    summary = json.loads((parent_dir / "summary.json").read_text(encoding="utf-8"))
    trace = json.loads((parent_dir / "multiagent_trace.json").read_text(encoding="utf-8"))

    assert (parent_dir / "final_answer.md").read_text(encoding="utf-8") == final
    assert (parent_dir / "trace.jsonl").is_file()
    assert (parent_dir / "multiagent_trace.json").is_file()
    assert summary["final_status"] == "completed"
    assert trace["status"] == "completed"
    assert trace["evidence_schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert trace["contract_validation_schema_version"] == CONTRACT_VALIDATION_SCHEMA_VERSION
    assert trace["contract_validation"] is None
    assert trace["failure_classification_schema_version"] == FAILURE_CLASSIFICATION_SCHEMA_VERSION
    assert trace["failure_classification"] is None
    assert summary["selected_implementer"] == "python_coder"
    assert summary["phases_executed"][:5] == [
        "planner",
        "researcher",
        "python_coder",
        "validator",
        "reviewer",
    ]
    assert run_json["prompt"] == "Make a Python change"
    assert run_json["parent_run_id"] == parent_dir.name
    assert run_json["child_runs"]
    assert all("child_run_id" in child for child in run_json["child_runs"])
    assert all(phase["status"] and phase["output"] for phase in run_json["phases"])
    coder_phase = next(phase for phase in trace["phases"] if phase["role"] == "python_coder")
    assert coder_phase["tool_calls"][0]["tool"] == "write_file"
    assert coder_phase["tool_calls"][0]["arguments"] == {"path": "x.py"}
    assert coder_phase["evidence_entries"][0]["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert coder_phase["evidence_entries"][0]["tool"] == "write_file"
    assert coder_phase["evidence_entries"][0]["target_path"] == "x.py"
    assert coder_phase["evidence_entries"][0]["source_run"]
    phase_run = parent_dir / "phases" / "01_planner" / "run.json"
    assert phase_run.is_file()
    assert (parent_dir / "phases" / "01_planner" / "output.md").is_file()
    assert (parent_dir / "phases" / "01_planner" / "tool_calls.jsonl").is_file()


def test_multiagent_parent_run_persists_failed_final_status(tmp_path, monkeypatch):
    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: implement x.py")
        if role == AgentRole.RESEARCHER:
            return _result(role, "Research: x.py is relevant")
        if role == AgentRole.GENERALIST_CODER:
            return _result(
                role,
                "Implemented x.py",
                tool_calls=[
                    {
                        "tool": "write_file",
                        "ok": True,
                        "arguments": {"path": "x.py"},
                        "output_preview": "wrote",
                    }
                ],
            )
        if role == AgentRole.VALIDATOR:
            return _result(role, "pytest passed")
        return _result(
            role,
            "However, there is insufficient evidence to confirm completion.",
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    final = run_multi_agent(
        "Make a Python change",
        default_selection("test:1b"),
        config=AgentConfig(
            cwd=str(tmp_path),
            runs_dir=str(tmp_path / "runs"),
            run_log_enabled=True,
        ),
    )

    parent_dir = next((tmp_path / "runs").glob("*/summary.json")).parent
    summary = json.loads((parent_dir / "summary.json").read_text(encoding="utf-8"))

    assert summary["final_status"] == "review_failed"
    assert "status: review_failed" in final
    assert (parent_dir / "final_answer.md").read_text(encoding="utf-8") == final


def test_multiagent_trace_records_role_anchor_and_allowed_tools(tmp_path, monkeypatch):
    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        return _result(
            role,
            "ok" if role != AgentRole.VALIDATOR else "pytest passed",
            attempt=attempt,
            role_anchor=f"Role anchor: You are currently acting as {role.value}.",
            allowed_tools=["read_file", "grep"],
            can_write=False,
            input_prompt=task_prompt,
            rounds=2,
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    cfg = AgentConfig(
        cwd=str(tmp_path),
        runs_dir=str(tmp_path / "runs"),
        run_log_enabled=True,
    )
    run_multi_agent("Inspect the repo", default_selection("test:1b"), config=cfg)

    trace_path = next((tmp_path / "runs").iterdir()) / "multiagent_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    planner = next(item for item in trace["phases"] if item["role"] == "planner")
    assert planner["role_anchor"].startswith("Role anchor:")
    assert planner["allowed_tools"] == ["read_file", "grep"]


def test_multiagent_trace_records_skipped_or_failed_phase(tmp_path, monkeypatch):
    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        if role == AgentRole.RESEARCHER:
            raise RuntimeError("research exploded")
        return _result(
            role,
            "ok",
            attempt=attempt,
            role_anchor=f"Role anchor: {role.value}",
            allowed_tools=[],
            input_prompt=task_prompt,
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    cfg = AgentConfig(
        cwd=str(tmp_path),
        runs_dir=str(tmp_path / "runs"),
        run_log_enabled=True,
    )
    with pytest.raises(RuntimeError, match="research exploded"):
        run_multi_agent("Inspect the repo", default_selection("test:1b"), config=cfg)

    trace_path = next((tmp_path / "runs").iterdir()) / "multiagent_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["failed_phase"] == "researcher"
    researcher = next(item for item in trace["phases"] if item["role"] == "researcher")
    assert researcher["status"] == "failed"
    assert "research exploded" in researcher["error"]


_WRITE_PROMPT = (
    "Crea un archivo llamado prueba_multiagente.txt en la raíz del workspace con "
    "exactamente este contenido: MULTIAGENTE_OK. Después verifica que el archivo "
    "existe y que el contenido es correcto. No modifiques ningún otro archivo."
)

_PYTHON_SCRIPT_OUTPUT = (
    '```python\nwith open("prueba_multiagente.txt", "w") as f:\n    f.write("MULTIAGENTE_OK")\n```'
)

_WRITE_READBACK_TOOL_CALLS = [
    {
        "tool": "write_file",
        "ok": True,
        "arguments": {"path": "prueba_multiagente.txt"},
        "output_preview": "Wrote prueba_multiagente.txt",
    },
    {
        "tool": "read_file",
        "ok": True,
        "arguments": {"path": "prueba_multiagente.txt"},
        "output_preview": "MULTIAGENTE_OK",
    },
]

_SCOPE_TOOL_CALLS = [
    {
        "tool": "git_status",
        "ok": True,
        "arguments": {"path": "."},
        "output_preview": "?? prueba_multiagente.txt",
    },
    {
        "tool": "git_diff",
        "ok": True,
        "arguments": {"path": "."},
        "output_preview": "(no tracked-file diff)",
    },
]


def _force_code_change_intent(monkeypatch) -> None:
    """Pin the intent decision so these orchestrator tests exercise the evidence
    gate, not the (separately tested) intent-routing classifier."""
    from ci2lab.harness.multiagent.intent import (
        MultiAgentIntent,
        MultiAgentIntentDecision,
    )

    decision = MultiAgentIntentDecision(
        intent=MultiAgentIntent.CODE_CHANGE,
        requires_write=True,
        allowed_phases=["planner", "researcher", "coder", "validator", "reviewer"],
        reason="forced code_change for orchestrator evidence-gate test",
        confidence="high",
    )
    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.classify_multiagent_intent",
        lambda _prompt: decision,
    )


def _write_run(implementation: SubAgentResult, validation_output: str) -> MultiAgentRun:
    run = MultiAgentRun(user_prompt=_WRITE_PROMPT)
    run.requires_write = True
    run.selected_coder_role = implementation.role
    run.add_result(_result(AgentRole.PLANNER, "Plan: create the file."))
    run.add_result(_result(AgentRole.RESEARCHER, "No existing target file."))
    run.add_result(implementation)
    run.add_result(_result(AgentRole.VALIDATOR, validation_output))
    return run


# --- Evidence-gate regression coverage ------------------------------------
#
# Root cause reproduced from run 2026-06-18_122425_20a4d28d: the coder returned
# a Python `open(..., "w")` script instead of calling write_file, so no tool
# evidence existed, yet the run was reported as completed because the validator
# text contained the substring "ok" (from MULTIAGENTE_OK).


def test_validation_failed_treats_insufficient_evidence_as_failure():
    assert validation_failed(
        _result(AgentRole.VALIDATOR, "Insufficient evidence: no write_file result.")
    )
    assert validation_failed(
        _result(AgentRole.VALIDATOR, "Insuficiente Evidencia. No hay evidencia de escritura.")
    )


def test_validation_failed_ignores_ok_substring_in_content():
    # The literal content token must not be read as a success ("ok" inside
    # MULTIAGENTE_OK) — this is the exact false-positive from the failing run.
    assert not validation_failed(_result(AgentRole.VALIDATOR, "Result content: MULTIAGENTE_OK"))
    # And when the validator reports insufficient evidence, the same content
    # token must not flip it back to success.
    assert validation_failed(
        _result(
            AgentRole.VALIDATOR,
            "No hay evidencia. MULTIAGENTE_OK. Insufficient evidence to confirm the write.",
        )
    )


def test_looks_like_untraceable_fs_mutation_detects_returned_script():
    assert looks_like_untraceable_fs_mutation(_PYTHON_SCRIPT_OUTPUT)
    assert looks_like_untraceable_fs_mutation('Path("x.txt").write_text("hi")')
    assert not looks_like_untraceable_fs_mutation("I will use write_file to create the file.")


def test_has_write_tool_evidence_requires_successful_write_tool():
    no_evidence = _result(AgentRole.GENERALIST_CODER, _PYTHON_SCRIPT_OUTPUT, tool_calls=[])
    assert not has_write_tool_evidence([no_evidence])

    failed_write = _result(
        AgentRole.GENERALIST_CODER,
        "tried",
        tool_calls=[{"tool": "write_file", "ok": False, "arguments": {"path": "x"}}],
    )
    assert not has_write_tool_evidence([failed_write])

    real_write = _result(AgentRole.GENERALIST_CODER, "done", tool_calls=_WRITE_READBACK_TOOL_CALLS)
    assert has_write_tool_evidence([real_write])


def test_write_task_lacks_evidence_for_returned_script_but_not_for_real_write():
    script_run = _write_run(
        _result(AgentRole.GENERALIST_CODER, _PYTHON_SCRIPT_OUTPUT, tool_calls=[]),
        "Insufficient evidence.",
    )
    assert write_task_lacks_evidence(script_run)
    assert final_run_status(script_run) != "completed"

    real_run = _write_run(
        _result(
            AgentRole.GENERALIST_CODER, "Created via tools.", tool_calls=_WRITE_READBACK_TOOL_CALLS
        ),
        "Validation passed.",
    )
    assert not write_task_lacks_evidence(real_run)
    assert final_run_status(real_run) == "completed"


def test_final_run_status_downgrades_write_task_without_evidence_even_if_validator_passes():
    # Even when the validator is fooled into reporting success, the deterministic
    # evidence gate must refuse a clean completion for a write task.
    fooled = _write_run(
        _result(AgentRole.GENERALIST_CODER, _PYTHON_SCRIPT_OUTPUT, tool_calls=[]),
        "All checks passed, looks ok.",
    )
    assert final_run_status(fooled) == "insufficient_evidence"


def test_implementation_and_repair_prompts_require_traceable_write_tools():
    plan = _result(AgentRole.PLANNER, "Create prueba_multiagente.txt.")
    research = _result(AgentRole.RESEARCHER, "No existing file.")
    impl_prompt = _build_implementation_prompt(_WRITE_PROMPT, plan, research)
    assert "write_file" in impl_prompt
    assert 'open(path, "w")' in impl_prompt
    assert "never executed" in impl_prompt

    repair_prompt = _build_repair_prompt(
        _WRITE_PROMPT,
        plan,
        research,
        _result(AgentRole.GENERALIST_CODER, _PYTHON_SCRIPT_OUTPUT),
        _result(AgentRole.VALIDATOR, "Insufficient evidence."),
    )
    assert "write_file" in repair_prompt
    assert 'open(path, "w")' in repair_prompt


def test_file_content_contract_instruction_is_added_to_implementation_prompt():
    plan = _result(AgentRole.PLANNER, "Create the requested file.")
    research = _result(AgentRole.RESEARCHER, "No existing file.")
    prompt = _build_implementation_prompt(
        "Create a file named notes/example.txt with exactly this content: OK",
        plan,
        research,
    )

    assert "File creation contract detected:" in prompt
    assert "write_file" in prompt
    assert "read_file" in prompt
    assert "Tool used: write_file" in prompt
    assert "Verification tool used: read_file" in prompt


def test_file_content_contract_instruction_is_not_added_to_general_write_prompt():
    plan = _result(AgentRole.PLANNER, "Make the requested change.")
    research = _result(AgentRole.RESEARCHER, "Relevant file: app.py")
    prompt = _build_implementation_prompt("Add tests and fix the bug", plan, research)

    assert "File creation contract detected:" not in prompt
    assert "Tool used: write_file" not in prompt
    assert "Verification tool used: read_file" not in prompt


def test_file_content_contract_instruction_is_added_to_repair_prompt():
    plan = _result(AgentRole.PLANNER, "Create the requested file.")
    research = _result(AgentRole.RESEARCHER, "No existing file.")
    repair_prompt = _build_repair_prompt(
        _WRITE_PROMPT,
        plan,
        research,
        _result(AgentRole.GENERALIST_CODER, "I described the file."),
        _result(AgentRole.VALIDATOR, "Insufficient evidence."),
    )

    assert "File creation contract detected:" in repair_prompt
    assert "Tool used: write_file" in repair_prompt
    assert "Verification tool used: read_file" in repair_prompt


def test_run_multi_agent_write_task_without_tool_evidence_is_not_completed(monkeypatch):
    _force_code_change_intent(monkeypatch)

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: create the file.")
        if role == AgentRole.RESEARCHER:
            return _result(role, "No existing target file.")
        if role == AgentRole.GENERALIST_CODER:
            return _result(role, _PYTHON_SCRIPT_OUTPUT, attempt=attempt, tool_calls=[])
        if role == AgentRole.VALIDATOR:
            return _result(role, "Insufficient evidence of the file write.", attempt=attempt)
        return _result(role, "Review complete.", attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        _WRITE_PROMPT,
        default_selection("test:1b"),
        config=AgentConfig(cwd=".", run_log_enabled=False),
        max_repair_attempts=0,
    )

    assert "status: completed" not in result
    assert "Selected implementer: generalist_coder" in result


def test_run_multi_agent_write_task_with_tool_evidence_completes(tmp_path, monkeypatch):
    _force_code_change_intent(monkeypatch)

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        if role == AgentRole.PLANNER:
            return _result(role, "Plan: create the file.")
        if role == AgentRole.RESEARCHER:
            return _result(role, "No existing target file.")
        if role == AgentRole.GENERALIST_CODER:
            (tmp_path / "prueba_multiagente.txt").write_text(
                "MULTIAGENTE_OK",
                encoding="utf-8",
            )
            return _result(
                role,
                "Created the file with tools.",
                attempt=attempt,
                tool_calls=_WRITE_READBACK_TOOL_CALLS,
            )
        if role == AgentRole.VALIDATOR:
            return _result(
                role,
                "Validation passed; content and scope are correct.",
                attempt=attempt,
                tool_calls=_SCOPE_TOOL_CALLS,
            )
        if role in {AgentRole.REVIEWER, AgentRole.SECURITY_REVIEWER}:
            return _result(
                role,
                "Review complete with real status/diff evidence.",
                attempt=attempt,
                tool_calls=_SCOPE_TOOL_CALLS,
            )
        return _result(role, "Review complete.", attempt=attempt)

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    result = run_multi_agent(
        _WRITE_PROMPT,
        default_selection("test:1b"),
        config=AgentConfig(cwd=str(tmp_path), run_log_enabled=False),
    )

    assert "status: completed" in result
    assert "Selected implementer: generalist_coder" in result


def test_multiagent_trace_truncates_large_tool_results(tmp_path, monkeypatch):
    huge = "x" * 5000

    def fake_run_subagent(role, task_prompt, selection, config, *, attempt=1):
        status_output = "pytest passed" if role == AgentRole.VALIDATOR else "ok"
        return _result(
            role,
            status_output,
            attempt=attempt,
            role_anchor=f"Role anchor: {role.value}",
            allowed_tools=["read_file"],
            input_prompt=task_prompt,
            tool_calls=[
                {
                    "tool": "read_file",
                    "ok": True,
                    "outcome": "approved",
                    "arguments": {"path": "big.txt"},
                    "output_preview": huge,
                    "error_preview": None,
                }
            ],
        )

    monkeypatch.setattr(
        "ci2lab.harness.multiagent.orchestrator.run_subagent",
        fake_run_subagent,
    )

    cfg = AgentConfig(
        cwd=str(tmp_path),
        runs_dir=str(tmp_path / "runs"),
        run_log_enabled=True,
    )
    run_multi_agent("Inspect the repo", default_selection("test:1b"), config=cfg)

    trace_path = next((tmp_path / "runs").iterdir()) / "multiagent_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    planner = next(item for item in trace["phases"] if item["role"] == "planner")
    preview = planner["tool_calls"][0]["output_preview"]
    assert len(preview) < 2000
    assert "truncated" in preview
