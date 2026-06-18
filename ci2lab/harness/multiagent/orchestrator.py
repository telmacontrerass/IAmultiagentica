"""Sequential multi-agent orchestrator.

This module is intentionally not wired into the default harness flow yet. The
classic `run_agent` path remains unchanged until the multi-agent route is
explicitly enabled by a later CLI/config integration.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from ci2lab.console import console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.multiagent.intent import classify_multiagent_intent
from ci2lab.harness.multiagent.roles import ROLE_SPECS
from ci2lab.harness.multiagent.runner import build_subagent_config, run_subagent
from ci2lab.harness.multiagent.state import AgentRole, MultiAgentRun, SubAgentResult
from ci2lab.harness.run_logger import RunLogger
from ci2lab.harness.types import AgentConfig

_VALIDATION_FAILURE_MARKERS = (
    "failed",
    "failure",
    "failing",
    "error",
    "traceback",
    "exception",
    "failed validation",
)

_VALIDATION_SUCCESS_MARKERS = (
    "passed",
    "pass",
    "success",
    "successful",
    "ok",
    "no errors",
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

TRACE_PROMPT_PREVIEW_CHARS = 1200
TRACE_OUTPUT_PREVIEW_CHARS = 1200

_READ_ONLY_TASK_MARKERS = (
    "read",
    "summarize",
    "summary",
    "extract",
    "explain",
    "analyze",
    "analyse",
    "inspect",
    "review",
    "access",
    "open",
)

_DOCUMENT_TASK_MARKERS = (
    "pdf",
    "docx",
    "document",
    "file",
)

_IMPLEMENTATION_TASK_MARKERS = (
    "add",
    "create",
    "write",
    "edit",
    "modify",
    "update",
    "implement",
    "fix",
    "change",
    "convert",
    "generate code",
)


def _combined_output(*results: SubAgentResult) -> str:
    return "\n\n".join(result.output for result in results if result.output)


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", text)
        for marker in markers
    )


def _role_label(role: AgentRole, attempt: int) -> str:
    suffix = f" attempt {attempt}" if attempt > 1 else ""
    return f"{role.value}{suffix}"


def _role_progress_label(role: AgentRole, attempt: int) -> str:
    labels = {
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
    }
    label = labels[role]
    return f"{label} (attempt {attempt})" if attempt > 1 else label


def subagent_blocked(result: SubAgentResult) -> bool:
    """Detect explicit subagent stop conditions."""
    text = result.output.strip().lower()
    return (
        result.status == "blocked"
        or text.startswith("blocked:")
        or "max rounds" in text
    )


def _preview_text(text: str | None, *, limit: int) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return value[:limit] + "… (truncated)"


def _hash_text(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _failure_status(exc: Exception) -> str:
    if "timeout" in str(exc).lower():
        return "timeout"
    return "failed"


def _failed_result(
    role: AgentRole,
    task_prompt: str,
    config: AgentConfig,
    *,
    attempt: int,
    error: str,
) -> SubAgentResult:
    stage_config = build_subagent_config(role, config)
    spec = ROLE_SPECS[role]
    return SubAgentResult(
        role=role,
        task=task_prompt,
        output="",
        status="timeout" if "timeout" in error.lower() else "failed",
        attempt=attempt,
        error=error,
        role_anchor=stage_config.role_anchor,
        allowed_tools=sorted(stage_config.skill_allowed_tools or ()),
        can_write=spec.can_write,
        input_prompt=_preview_text(task_prompt, limit=TRACE_PROMPT_PREVIEW_CHARS),
    )


def _skipped_result(
    role: AgentRole,
    task_prompt: str,
    config: AgentConfig,
    *,
    reason: str,
) -> SubAgentResult:
    stage_config = build_subagent_config(role, config)
    spec = ROLE_SPECS[role]
    return SubAgentResult(
        role=role,
        task=task_prompt,
        output="",
        status="skipped",
        attempt=1,
        error=None,
        role_anchor=stage_config.role_anchor,
        allowed_tools=sorted(stage_config.skill_allowed_tools or ()),
        can_write=spec.can_write,
        input_prompt=_preview_text(task_prompt, limit=TRACE_PROMPT_PREVIEW_CHARS),
        skipped_reason=reason,
    )


def _phase_trace(result: SubAgentResult) -> dict[str, object]:
    tool_calls = [
        {
            "tool": entry.get("tool"),
            "ok": entry.get("ok"),
            "outcome": entry.get("outcome"),
            "arguments": entry.get("arguments") or {},
            "output_preview": _preview_text(
                str(entry.get("output_preview", "")),
                limit=TRACE_OUTPUT_PREVIEW_CHARS,
            ),
            "error_preview": _preview_text(
                str(entry.get("error_preview", "")),
                limit=TRACE_OUTPUT_PREVIEW_CHARS,
            )
            if entry.get("error_preview")
            else None,
        }
        for entry in result.tool_calls
    ]
    return {
        "role": result.role.value,
        "phase": result.role.value,
        "attempt": result.attempt,
        "status": result.status,
        "error": result.error,
        "skipped_reason": result.skipped_reason,
        "role_anchor": result.role_anchor,
        "allowed_tools": result.allowed_tools,
        "can_write": result.can_write,
        "input_prompt_preview": _preview_text(
            result.input_prompt or result.task,
            limit=TRACE_PROMPT_PREVIEW_CHARS,
        ),
        "input_prompt_hash": _hash_text(result.task),
        "tool_calls": tool_calls,
        "final_output_preview": _preview_text(
            result.output,
            limit=TRACE_OUTPUT_PREVIEW_CHARS,
        ),
        "final_output_hash": _hash_text(result.output),
        "duration_ms": result.duration_ms,
        "rounds": result.rounds,
        "run_dir": result.subagent_run_dir,
    }


def _trace_payload(
    run: MultiAgentRun,
    selection: ModelSelection,
    config: AgentConfig,
    *,
    started_at: datetime,
    ended_at: datetime,
) -> dict[str, object]:
    phases = [_phase_trace(result) for result in run.results]
    planned_phases: list[str] = list(run.planned_phases) or [
        AgentRole.PLANNER.value,
        AgentRole.RESEARCHER.value,
    ]
    # Resolve the generic "coder" placeholder to the concrete implementer role.
    if run.selected_coder_role is not None and "coder" in planned_phases:
        planned_phases[planned_phases.index("coder")] = run.selected_coder_role.value
    if (
        any(
            result.role == AgentRole.SECURITY_REVIEWER and result.status != "skipped"
            for result in run.results
        )
        and AgentRole.SECURITY_REVIEWER.value not in planned_phases
    ):
        planned_phases.append(AgentRole.SECURITY_REVIEWER.value)
    executed_phases = [result.role.value for result in run.results if result.status != "skipped"]
    failed_phase = next(
        (result.role.value for result in run.results if result.status in {"failed", "timeout", "blocked"}),
        run.failed_phase,
    )
    if failed_phase is None:
        last_validation = run.latest_for(AgentRole.VALIDATOR)
        if last_validation and validation_failed(last_validation):
            failed_phase = AgentRole.VALIDATOR.value
    trace_status = "failed" if run.error else "completed"
    last_validation = run.latest_for(AgentRole.VALIDATOR)
    if trace_status == "completed" and last_validation and validation_failed(last_validation):
        trace_status = "validation_failed"
    return {
        "timestamp": started_at.isoformat(),
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": round((ended_at - started_at).total_seconds(), 3),
        "user_prompt": run.user_prompt,
        "user_prompt_hash": _hash_text(run.user_prompt),
        "model": selection.ollama_tag,
        "model_id": selection.model_id,
        "tool_mode": selection.tool_mode,
        "workspace": config.cwd,
        "intent": run.intent,
        "requires_write": run.requires_write,
        "intent_reason": run.intent_reason,
        "intent_confidence": run.intent_confidence,
        "review_only": run.intent == "review_only",
        "read_only": run.intent == "read_only_answer",
        "selected_coder_role": run.selected_coder_role.value if run.selected_coder_role else None,
        "planned_phases": planned_phases,
        "executed_phases": executed_phases,
        "failed_phase": failed_phase,
        "error": run.error,
        "status": trace_status,
        "phases": phases,
    }


def _run_subagent_stage(
    role: AgentRole,
    task_prompt: str,
    selection: ModelSelection,
    config: AgentConfig,
    *,
    attempt: int = 1,
) -> SubAgentResult:
    label = _role_label(role, attempt)
    console.print(f"[cyan][multi-agent][/cyan] {_role_progress_label(role, attempt)}...")
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


def _execute_phase(
    state: MultiAgentRun,
    role: AgentRole,
    task_prompt: str,
    selection: ModelSelection,
    config: AgentConfig,
    *,
    attempt: int = 1,
) -> SubAgentResult:
    try:
        result = _run_subagent_stage(
            role,
            task_prompt,
            selection,
            config,
            attempt=attempt,
        )
    except Exception as exc:
        state.failed_phase = role.value
        state.error = str(exc)
        failed = _failed_result(
            role,
            task_prompt,
            config,
            attempt=attempt,
            error=str(exc),
        )
        state.add_result(failed)
        raise
    state.add_result(result)
    if subagent_blocked(result):
        state.failed_phase = role.value
        state.error = result.output or result.error
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


def should_skip_implementation(
    user_prompt: str,
    plan: SubAgentResult,
    research: SubAgentResult,
) -> bool:
    """Return true when the request only needs information gathering."""
    prompt = user_prompt.lower()
    if _contains_marker(prompt, _IMPLEMENTATION_TASK_MARKERS):
        return False
    has_read_intent = _contains_marker(prompt, _READ_ONLY_TASK_MARKERS)
    has_document_target = _contains_marker(prompt, _DOCUMENT_TASK_MARKERS)
    if has_read_intent and has_document_target:
        return True

    evidence = _combined_output(plan, research).lower()
    if _contains_marker(evidence, _IMPLEMENTATION_TASK_MARKERS):
        return False
    return (
        _contains_marker(evidence, _READ_ONLY_TASK_MARKERS)
        and _contains_marker(evidence, _DOCUMENT_TASK_MARKERS)
    )


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
        "Create the authoritative execution plan for this task. The rest of "
        "the subagents must follow your plan, so make the delegation explicit.\n\n"
        "Your plan must include these sections:\n"
        "1. Goal\n"
        "2. Ordered steps\n"
        "3. Role assignments: one bullet per needed role, with the exact task "
        "that role owns\n"
        "4. Dependencies: what each role must wait for or use from previous roles\n"
        "5. Boundaries: files or responsibilities each role must not touch\n"
        "6. Success criteria\n\n"
        "Keep role ownership non-overlapping. If the task is read-only, say so "
        "and assign no implementation role.\n\n"
        f"User task:\n{user_prompt}"
    )


def _build_research_prompt(user_prompt: str, plan: SubAgentResult | None) -> str:
    plan_text = plan.output if plan else "No explicit plan was produced for this task."
    return (
        "Follow the planner's execution plan. Only perform the research/context "
        "gathering assigned to the researcher role. Do not take over coding, "
        "validation, or review responsibilities, and do not modify files.\n\n"
        "Report:\n"
        "- which planner-assigned researcher tasks you completed\n"
        "- relevant files, APIs, constraints, and risks\n"
        "- any missing dependency as `BLOCKED:` if the plan cannot continue\n\n"
        f"User task:\n{user_prompt}\n\nPlan:\n{plan_text}"
    )


def _build_implementation_prompt(
    user_prompt: str,
    plan: SubAgentResult,
    research: SubAgentResult,
) -> str:
    return (
        "Follow the planner's execution plan and the researcher findings. "
        "Implement only the tasks assigned to your implementer role. Do not "
        "take over validation, review, security review, or unrelated role "
        "responsibilities. Do not touch files or areas outside the planner's "
        "boundaries unless the research context proves they are required; if "
        "that happens, explain why.\n\n"
        "If a dependency from the plan or research is missing, return `BLOCKED:` "
        "with the exact missing dependency instead of guessing.\n\n"
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
        "Follow the planner's validation expectations. Validate only the "
        "implemented work against the plan, research findings, and success "
        "criteria. Run focused tests or checks when possible. Clearly state "
        "whether validation passed or failed, and include actionable failure "
        "details tied to the plan.\n\n"
        "If the implementation did not follow the plan, report validation as "
        "failed and explain the mismatch.\n\n"
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
        "staying within the same implementer role and the planner's assigned "
        "boundaries. Address the validation output directly and keep unrelated "
        "behavior unchanged.\n\n"
        "If the repair would require work outside your assigned role or files, "
        "return `BLOCKED:` with the reason instead of expanding scope.\n\n"
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
        "Review the completed multi-agent run against the planner's execution "
        "plan. Check whether each subagent stayed within its assigned task, "
        "respected dependencies, avoided overlapping responsibilities, and met "
        "the success criteria. Identify remaining risks, missing tests, "
        "regressions, or incomplete requirements. Do not modify files.\n\n"
        f"User task:\n{run.user_prompt}\n\nRun evidence:\n{evidence}"
    )


def _build_security_review_prompt(run: MultiAgentRun) -> str:
    evidence = "\n\n".join(
        f"[{result.role.value} attempt {result.attempt}]\n{result.output}"
        for result in run.results
    )
    return (
        "Review the completed multi-agent run specifically for security and "
        "permission risks, using the planner's boundaries as the source of "
        "truth. Check command execution, filesystem writes, secret handling, "
        "approval behavior, path safety, and whether any role exceeded its "
        "assigned scope. Do not modify files.\n\n"
        f"User task:\n{run.user_prompt}\n\nRun evidence:\n{evidence}"
    )


def synthesize_final_answer(run: MultiAgentRun) -> str:
    """Create a concise final answer from orchestrator state."""
    blocked = next((result for result in run.results if subagent_blocked(result)), None)
    if blocked:
        return (
            "Multi-agent run finished with status: blocked\n"
            f"Blocked role: {blocked.role.value}\n\n"
            f"Reason:\n{blocked.output or blocked.error or 'No reason provided.'}"
        )

    research = run.latest_for(AgentRole.RESEARCHER)
    last_validation = run.latest_for(AgentRole.VALIDATOR)
    reviewer = run.latest_for(AgentRole.REVIEWER)
    security_reviewer = run.latest_for(AgentRole.SECURITY_REVIEWER)
    status = (
        "validation_failed"
        if last_validation and validation_failed(last_validation)
        else "completed"
    )
    coder = (
        run.selected_coder_role.value
        if run.selected_coder_role
        else "none (read-only task)"
    )
    review_text = reviewer.output if reviewer else "No reviewer output was produced."
    security_text = (
        f"\n\nSecurity review:\n{security_reviewer.output}"
        if security_reviewer
        else ""
    )
    validation_text = (
        last_validation.output if last_validation else "No validation output was produced."
    )
    if run.selected_coder_role is None:
        research_text = (
            research.output if research else "No research output was produced."
        )
        return (
            f"Multi-agent run finished with status: completed\n"
            f"Selected implementer: {coder}\n\n"
            f"Research:\n{research_text}\n\n"
            f"Review:\n{review_text}"
            f"{security_text}"
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

    # Deterministic pre-orchestration intent gate (NVIDIA-style intent routing).
    # Decide which phases are allowed *before* building or executing any phase.
    decision = classify_multiagent_intent(user_prompt)
    planned_phases = list(decision.allowed_phases)
    state.intent = decision.intent.value
    state.requires_write = decision.requires_write
    state.intent_reason = decision.reason
    state.intent_confidence = decision.confidence
    state.planned_phases = planned_phases
    console.print(
        f"[cyan][multi-agent][/cyan] intent={decision.intent.value} "
        f"requires_write={decision.requires_write} phases={planned_phases}"
    )

    started_at = datetime.now(timezone.utc)
    run_log = RunLogger.maybe_create(cfg, selection, user_prompt)
    if run_log:
        run_log.start()

    final_status = "success"
    try:
        plan: SubAgentResult | None = None
        if "planner" in planned_phases:
            plan_prompt = _build_planner_prompt(user_prompt)
            plan = _execute_phase(
                state,
                AgentRole.PLANNER,
                plan_prompt,
                selection,
                cfg,
            )
            if subagent_blocked(plan):
                state.final_answer = synthesize_final_answer(state)
                return state.final_answer

        research: SubAgentResult | None = None
        if "researcher" in planned_phases:
            research_prompt = _build_research_prompt(user_prompt, plan)
            research = _execute_phase(
                state,
                AgentRole.RESEARCHER,
                research_prompt,
                selection,
                cfg,
            )
            if subagent_blocked(research):
                state.final_answer = synthesize_final_answer(state)
                return state.final_answer

        # Implementation + validation only run when the intent allows writes.
        if "coder" in planned_phases:
            coder_role = choose_coder_role(plan, research)
            state.selected_coder_role = coder_role

            implementation_prompt = _build_implementation_prompt(user_prompt, plan, research)
            implementation = _execute_phase(
                state,
                coder_role,
                implementation_prompt,
                selection,
                cfg,
            )
            if subagent_blocked(implementation):
                state.final_answer = synthesize_final_answer(state)
                return state.final_answer

            if "validator" in planned_phases:
                validation_prompt = _build_validation_prompt(
                    user_prompt, plan, research, implementation
                )
                validation = _execute_phase(
                    state,
                    AgentRole.VALIDATOR,
                    validation_prompt,
                    selection,
                    cfg,
                )
                if subagent_blocked(validation):
                    state.final_answer = synthesize_final_answer(state)
                    return state.final_answer

                repair_attempt = 0
                while validation_failed(validation) and repair_attempt < max_repair_attempts:
                    repair_attempt += 1
                    repair_prompt = _build_repair_prompt(
                        user_prompt,
                        plan,
                        research,
                        implementation,
                        validation,
                    )
                    implementation = _execute_phase(
                        state,
                        coder_role,
                        repair_prompt,
                        selection,
                        cfg,
                        attempt=repair_attempt + 1,
                    )
                    if subagent_blocked(implementation):
                        state.final_answer = synthesize_final_answer(state)
                        return state.final_answer

                    validation_prompt = _build_validation_prompt(
                        user_prompt,
                        plan,
                        research,
                        implementation,
                    )
                    validation = _execute_phase(
                        state,
                        AgentRole.VALIDATOR,
                        validation_prompt,
                        selection,
                        cfg,
                        attempt=repair_attempt + 1,
                    )
                    if subagent_blocked(validation):
                        state.final_answer = synthesize_final_answer(state)
                        return state.final_answer

        if "reviewer" in planned_phases:
            review_prompt = _build_review_prompt(state)
            review = _execute_phase(
                state,
                AgentRole.REVIEWER,
                review_prompt,
                selection,
                cfg,
            )
            if subagent_blocked(review):
                state.final_answer = synthesize_final_answer(state)
                return state.final_answer

            if should_run_security_review(state):
                security_prompt = _build_security_review_prompt(state)
                security_review = _execute_phase(
                    state,
                    AgentRole.SECURITY_REVIEWER,
                    security_prompt,
                    selection,
                    cfg,
                )
                if subagent_blocked(security_review):
                    state.final_answer = synthesize_final_answer(state)
                    return state.final_answer
            else:
                state.add_result(
                    _skipped_result(
                        AgentRole.SECURITY_REVIEWER,
                        "Security review was not required for this run.",
                        cfg,
                        reason="Security-sensitive markers were not detected.",
                    )
                )

        state.final_answer = synthesize_final_answer(state)
        return state.final_answer
    except Exception as exc:
        final_status = "llm_error"
        state.error = str(exc)
        if state.failed_phase is None:
            state.failed_phase = state.results[-1].role.value if state.results else None
        raise
    finally:
        ended_at = datetime.now(timezone.utc)
        if run_log and run_log.run_dir is not None:
            run_log.write_json_artifact(
                "multiagent_trace.json",
                _trace_payload(
                    state,
                    selection,
                    cfg,
                    started_at=started_at,
                    ended_at=ended_at,
                ),
            )
            run_log.finalize(
                status=final_status,
                final_answer=state.final_answer or "",
                conversation=[
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": state.final_answer or state.error or ""},
                ],
                error=state.error,
            )
