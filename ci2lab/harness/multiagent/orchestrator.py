"""Sequential multi-agent orchestrator.

This module is intentionally not wired into the default harness flow yet. The
classic `run_agent` path remains unchanged until the multi-agent route is
explicitly enabled by a later CLI/config integration.
"""

from __future__ import annotations

from ci2lab.console import console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.multiagent.runner import run_subagent
from ci2lab.harness.multiagent.state import AgentRole, MultiAgentRun, SubAgentResult
from ci2lab.harness.types import AgentConfig

_VALIDATION_FAILURE_MARKERS = (
    "failed",
    "failure",
    "failing",
    "error",
    "traceback",
    "exception",
    "no pasa",
    "fallo",
    "falla",
    "failed validation",
)

_VALIDATION_SUCCESS_MARKERS = (
    "passed",
    "pass",
    "success",
    "successful",
    "ok",
    "no errors",
    "sin errores",
    "todo pasa",
)

_SECURITY_REVIEW_MARKERS = (
    "security",
    "permission",
    "permissions",
    "secret",
    "token",
    "bash",
    "shell",
    "write_file",
    "edit_file",
    "filesystem",
    "path traversal",
    "approval",
    "deny",
    "allow",
)


def _combined_output(*results: SubAgentResult) -> str:
    return "\n\n".join(result.output for result in results if result.output)


def _role_label(role: AgentRole, attempt: int) -> str:
    suffix = f" attempt {attempt}" if attempt > 1 else ""
    return f"{role.value}{suffix}"


def _run_subagent_stage(
    role: AgentRole,
    task_prompt: str,
    selection: ModelSelection,
    config: AgentConfig,
    *,
    attempt: int = 1,
) -> SubAgentResult:
    label = _role_label(role, attempt)
    console.print(f"[cyan][multi-agent][/cyan] starting {label}")
    try:
        result = run_subagent(
            role,
            task_prompt,
            selection,
            config,
            attempt=attempt,
        )
    except Exception:
        console.print(f"[red][multi-agent][/red] failed {label}")
        raise
    console.print(f"[green][multi-agent][/green] completed {label}")
    return result


def choose_coder_role(plan: SubAgentResult, research: SubAgentResult) -> AgentRole:
    """Choose an implementation role from planner/researcher evidence."""
    text = _combined_output(plan, research).lower()
    if any(marker in text for marker in ("readme", ".md", "docs/", "documentacion")):
        return AgentRole.DOCS_CODER
    if any(marker in text for marker in ("pytest", "tests/", "test_", "unit test")):
        return AgentRole.TEST_CODER
    if any(
        marker in text
        for marker in ("frontend", "javascript", ".js", ".html", ".css", "ui/static")
    ):
        return AgentRole.FRONTEND_CODER
    if any(marker in text for marker in (".py", "python", "ci2lab/", "harness")):
        return AgentRole.PYTHON_CODER
    return AgentRole.GENERALIST_CODER


def validation_failed(validation: SubAgentResult) -> bool:
    """Best-effort validation classifier for the first sequential version."""
    output = validation.output.lower()
    has_success = any(marker in output for marker in _VALIDATION_SUCCESS_MARKERS)
    has_failure = any(marker in output for marker in _VALIDATION_FAILURE_MARKERS)
    if has_success:
        return False
    return has_failure


def should_run_security_review(run: MultiAgentRun) -> bool:
    """Decide whether the optional security reviewer should run."""
    text = "\n\n".join(
        [run.user_prompt]
        + [result.output for result in run.results]
    ).lower()
    return any(marker in text for marker in _SECURITY_REVIEW_MARKERS)


def _build_planner_prompt(user_prompt: str) -> str:
    return (
        "Create an ordered plan for this task. Include likely files/areas, "
        "dependencies, success criteria, and the kind of implementer needed.\n\n"
        f"User task:\n{user_prompt}"
    )


def _build_research_prompt(user_prompt: str, plan: SubAgentResult) -> str:
    return (
        "Inspect the repository context needed for this plan. Summarize relevant "
        "files, APIs, constraints, and risks. Do not modify files.\n\n"
        f"User task:\n{user_prompt}\n\nPlan:\n{plan.output}"
    )


def _build_implementation_prompt(
    user_prompt: str,
    plan: SubAgentResult,
    research: SubAgentResult,
) -> str:
    return (
        "Implement the requested change using the plan and research context. "
        "Keep the change focused and preserve existing behavior.\n\n"
        f"User task:\n{user_prompt}\n\nPlan:\n{plan.output}\n\n"
        f"Research:\n{research.output}"
    )


def _build_validation_prompt(
    user_prompt: str,
    plan: SubAgentResult,
    research: SubAgentResult,
    implementation: SubAgentResult,
) -> str:
    return (
        "Validate the implementation. Run focused tests or checks when possible. "
        "Clearly state whether validation passed or failed, and include actionable "
        "failure details.\n\n"
        f"User task:\n{user_prompt}\n\nPlan:\n{plan.output}\n\n"
        f"Research:\n{research.output}\n\nImplementation:\n{implementation.output}"
    )


def _build_repair_prompt(
    user_prompt: str,
    plan: SubAgentResult,
    research: SubAgentResult,
    previous_implementation: SubAgentResult,
    validation: SubAgentResult,
) -> str:
    return (
        "The validator reported a failure. Repair the implementation while "
        "staying within the same implementer role. Address the validation output "
        "directly and keep unrelated behavior unchanged.\n\n"
        f"User task:\n{user_prompt}\n\nPlan:\n{plan.output}\n\n"
        f"Research:\n{research.output}\n\nPrevious implementation:\n"
        f"{previous_implementation.output}\n\nValidation failure:\n"
        f"{validation.output}"
    )


def _build_review_prompt(run: MultiAgentRun) -> str:
    evidence = "\n\n".join(
        f"[{result.role.value} attempt {result.attempt}]\n{result.output}"
        for result in run.results
    )
    return (
        "Review the completed multi-agent run. Identify remaining risks, missing "
        "tests, regressions, or incomplete requirements. Do not modify files.\n\n"
        f"User task:\n{run.user_prompt}\n\nRun evidence:\n{evidence}"
    )


def _build_security_review_prompt(run: MultiAgentRun) -> str:
    evidence = "\n\n".join(
        f"[{result.role.value} attempt {result.attempt}]\n{result.output}"
        for result in run.results
    )
    return (
        "Review the completed multi-agent run specifically for security and "
        "permission risks. Check command execution, filesystem writes, secret "
        "handling, approval behavior, and path safety. Do not modify files.\n\n"
        f"User task:\n{run.user_prompt}\n\nRun evidence:\n{evidence}"
    )


def synthesize_final_answer(run: MultiAgentRun) -> str:
    """Create a concise final answer from orchestrator state."""
    last_validation = run.latest_for(AgentRole.VALIDATOR)
    reviewer = run.latest_for(AgentRole.REVIEWER)
    security_reviewer = run.latest_for(AgentRole.SECURITY_REVIEWER)
    status = (
        "validation_failed"
        if last_validation and validation_failed(last_validation)
        else "completed"
    )
    coder = run.selected_coder_role.value if run.selected_coder_role else "unknown"
    review_text = reviewer.output if reviewer else "No reviewer output was produced."
    security_text = (
        f"\n\nSecurity review:\n{security_reviewer.output}"
        if security_reviewer
        else ""
    )
    validation_text = (
        last_validation.output if last_validation else "No validation output was produced."
    )
    return (
        f"Multi-agent run finished with status: {status}\n"
        f"Selected implementer: {coder}\n\n"
        f"Validation:\n{validation_text}\n\n"
        f"Review:\n{review_text}"
        f"{security_text}"
    )


def run_multi_agent(
    user_prompt: str,
    selection: ModelSelection,
    *,
    config: AgentConfig | None = None,
    max_repair_attempts: int = 2,
) -> str:
    """Run the first sequential multi-agent flow."""
    cfg = config or AgentConfig(cwd=".")
    state = MultiAgentRun(user_prompt=user_prompt)

    plan = _run_subagent_stage(
        AgentRole.PLANNER,
        _build_planner_prompt(user_prompt),
        selection,
        cfg,
    )
    state.add_result(plan)

    research = _run_subagent_stage(
        AgentRole.RESEARCHER,
        _build_research_prompt(user_prompt, plan),
        selection,
        cfg,
    )
    state.add_result(research)

    coder_role = choose_coder_role(plan, research)
    state.selected_coder_role = coder_role

    implementation = _run_subagent_stage(
        coder_role,
        _build_implementation_prompt(user_prompt, plan, research),
        selection,
        cfg,
    )
    state.add_result(implementation)

    validation = _run_subagent_stage(
        AgentRole.VALIDATOR,
        _build_validation_prompt(user_prompt, plan, research, implementation),
        selection,
        cfg,
    )
    state.add_result(validation)

    repair_attempt = 0
    while validation_failed(validation) and repair_attempt < max_repair_attempts:
        repair_attempt += 1
        implementation = _run_subagent_stage(
            coder_role,
            _build_repair_prompt(
                user_prompt,
                plan,
                research,
                implementation,
                validation,
            ),
            selection,
            cfg,
            attempt=repair_attempt + 1,
        )
        state.add_result(implementation)

        validation = _run_subagent_stage(
            AgentRole.VALIDATOR,
            _build_validation_prompt(user_prompt, plan, research, implementation),
            selection,
            cfg,
            attempt=repair_attempt + 1,
        )
        state.add_result(validation)

    review = _run_subagent_stage(
        AgentRole.REVIEWER,
        _build_review_prompt(state),
        selection,
        cfg,
    )
    state.add_result(review)

    if should_run_security_review(state):
        security_review = _run_subagent_stage(
            AgentRole.SECURITY_REVIEWER,
            _build_security_review_prompt(state),
            selection,
            cfg,
        )
        state.add_result(security_review)

    state.final_answer = synthesize_final_answer(state)
    return state.final_answer
