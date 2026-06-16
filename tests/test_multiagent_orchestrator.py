from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.multiagent.orchestrator import (
    choose_coder_role,
    run_multi_agent,
    should_run_security_review,
    validation_failed,
)
from ci2lab.harness.multiagent.state import AgentRole, SubAgentResult


def _result(role: AgentRole, output: str, *, attempt: int = 1) -> SubAgentResult:
    return SubAgentResult(
        role=role,
        task=f"{role.value} task",
        output=output,
        attempt=attempt,
    )


def test_choose_coder_role_prefers_specific_evidence():
    plan = _result(AgentRole.PLANNER, "Update ci2lab/harness/orchestrator.py")
    research = _result(AgentRole.RESEARCHER, "This is Python harness code.")

    assert choose_coder_role(plan, research) == AgentRole.PYTHON_CODER

    plan = _result(AgentRole.PLANNER, "Update ui/static/app.js and styles.css")
    research = _result(AgentRole.RESEARCHER, "Frontend behavior.")

    assert choose_coder_role(plan, research) == AgentRole.FRONTEND_CODER


def test_validation_failed_detects_failure_and_pass():
    assert validation_failed(_result(AgentRole.VALIDATOR, "pytest failed"))
    assert not validation_failed(_result(AgentRole.VALIDATOR, "pytest passed"))
    assert not validation_failed(_result(AgentRole.VALIDATOR, "no errors"))


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
