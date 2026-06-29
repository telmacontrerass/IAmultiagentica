import json

import pytest

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.multiagent.orchestrator import (
    _build_implementation_prompt,
    _build_planner_prompt,
    _build_research_prompt,
    _build_review_prompt,
    _build_validation_prompt,
    choose_coder_role,
    run_multi_agent,
    should_run_security_review,
    should_skip_implementation,
    subagent_blocked,
    validation_failed,
)
from ci2lab.harness.multiagent.state import AgentRole, SubAgentResult


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
