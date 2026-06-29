"""Sequential multi-agent orchestrator.

This module is intentionally not wired into the default harness flow yet. The
classic `run_agent` path remains unchanged until the multi-agent route is
explicitly enabled by a later CLI/config integration.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ci2lab.console import console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.multiagent.context_budget import (
    assess_feasibility,
    chunk_anchored_text,
    infeasible_message,
    plan_chunks,
    recommended_context_for,
    total_manuscript_chars,
)
from ci2lab.harness.multiagent.grounding import (
    Finding,
    VerificationBuckets,
    extract_fetch_attempts,
    parse_findings,
    regroundable,
    verify_findings,
)
from ci2lab.harness.multiagent.intent import MultiAgentIntent, classify_multiagent_intent
from ci2lab.harness.multiagent.paper_review import (
    REFUSAL_MESSAGE,
    QualitySignals,
    ReviewContext,
    assemble_report,
    assess_quality,
    build_groundedness_prompt,
    build_intake_prompt,
    build_lens_prompt,
    build_reground_prompt,
    build_revision_plan_prompt,
    quality_abort_message,
)
from ci2lab.harness.multiagent.roles import ROLE_SPECS
from ci2lab.harness.multiagent.runner import build_subagent_config, run_subagent
from ci2lab.harness.multiagent.state import AgentRole, MultiAgentRun, SubAgentResult
from ci2lab.harness.run_logger import RunLogger
from ci2lab.harness.types import AgentConfig

# Ordered read-only lenses that run after intake in the grounded paper review.
_PAPER_REVIEW_LENSES = (
    AgentRole.SCOPE_REVIEWER,
    AgentRole.NOVELTY_REVIEWER,
    AgentRole.METHODOLOGY_REVIEWER,
    AgentRole.FIELD_EXPERT_REVIEWER,
    AgentRole.ADVERSARIAL_REVIEWER,
    AgentRole.FORMAT_REVIEWER,
)

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
    "complete",
    "solve",
    "develop",
    "build",
)

# The roles that actually produce the deliverable: the researcher (gathers the
# only context the coder sees) plus every implementer (any role that can write).
# Only a block from one of these marks the whole run blocked — the planner,
# validator, reviewer, and security reviewer are advisory, so their confusion
# (e.g. a validator that replies "BLOCKED: please provide a validation step")
# must never abort a run whose researcher and coder already did real work.
# Derived from ROLE_SPECS so adding a new implementer role can never silently
# fall out of this set.
_LOAD_BEARING_ROLES = frozenset(
    {AgentRole.RESEARCHER} | {role for role, spec in ROLE_SPECS.items() if spec.can_write}
)

# A request is test-centric or docs-centric only when the USER asks for tests or
# docs as the deliverable — matched against the user's own prompt, never against
# planner/researcher evidence. An "implement/complete/solve" task that merely
# mentions that unit tests are required (e.g. an exam statement) must not be
# routed to the test-only coder, which would leave the actual program unwritten.
_TEST_REQUEST_RE = re.compile(
    r"\bunit tests?\b|\bpytest\b|\btest (case|suite|coverage|file)s?\b|"
    r"\b(write|add|create|update|run|fix|implement|generate)\b[^.\n]{0,30}\btests?\b",
    re.IGNORECASE,
)
_DOCS_REQUEST_RE = re.compile(
    r"\breadme\b|\bchangelog\b|\bdocumentation\b|\bdocstrings?\b|\bdocs?\b|\.md\b",
    re.IGNORECASE,
)
_FRONTEND_EVIDENCE = ("frontend", "javascript", ".js", ".html", ".css", "ui/static")
_PYTHON_EVIDENCE = (".py", "python", "ci2lab/", "harness")


def _combined_output(*results: SubAgentResult | None) -> str:
    """Join the non-empty outputs of the given results with blank-line separators."""
    return "\n\n".join(result.output for result in results if result is not None and result.output)


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    """True if any marker appears in ``text`` as a whole word (word-boundary match)."""
    return any(re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", text) for marker in markers)


def _role_label(role: AgentRole, attempt: int) -> str:
    """Build a short trace label for a role, appending the attempt number when > 1."""
    suffix = f" attempt {attempt}" if attempt > 1 else ""
    return f"{role.value}{suffix}"


def _role_progress_label(role: AgentRole, attempt: int) -> str:
    """Build a human-friendly progress label for a role and attempt number."""
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
    label = labels[role]
    return f"{label} (attempt {attempt})" if attempt > 1 else label


def subagent_blocked(result: SubAgentResult) -> bool:
    """Detect explicit subagent stop conditions."""
    text = result.output.strip().lower()
    return result.status == "blocked" or text.startswith("blocked:") or "max rounds" in text


def _preview_text(text: str | None, *, limit: int) -> str:
    """Return ``text`` truncated to ``limit`` characters with a marker when longer."""
    value = text or ""
    if len(value) <= limit:
        return value
    return value[:limit] + "… (truncated)"


def _hash_text(text: str | None) -> str | None:
    """Return the SHA-256 hex digest of ``text``, or ``None`` when it is ``None``."""
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _failure_status(exc: Exception) -> str:
    """Classify an exception as ``"timeout"`` or ``"failed"`` from its message."""
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
    """Build a placeholder result for a phase that raised before producing output."""
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
    """Build a placeholder result for a phase that was deliberately skipped."""
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
    """Build the JSON-serializable trace record for a single executed phase."""
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
    """Build the full multi-agent trace payload written to ``multiagent_trace.json``."""
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
        (
            result.role.value
            for result in run.results
            if result.status in {"failed", "timeout", "blocked"}
        ),
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
    on_progress: Callable[[str], None] | None = None,
) -> SubAgentResult:
    """Run one subagent stage with progress/console reporting around the call."""
    label = _role_label(role, attempt)
    progress_label = _role_progress_label(role, attempt)
    if on_progress:
        on_progress(progress_label)
    else:
        console.print(f"[cyan][multi-agent][/cyan] {progress_label}...")
    try:
        kwargs: dict[str, Any] = {"attempt": attempt}
        if on_progress:
            kwargs["on_progress"] = on_progress
        result = run_subagent(role, task_prompt, selection, config, **kwargs)
    except Exception:
        if on_progress:
            on_progress("")
        else:
            console.print(f"[red][multi-agent][/red] failed {label}")
        raise
    if not on_progress:
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
    on_progress: Callable[[str], None] | None = None,
) -> SubAgentResult:
    """Run a phase, record its result on ``state``, and flag load-bearing blocks.

    Re-raises any exception from the stage after recording a failed result on the
    run state.
    """
    try:
        result = _run_subagent_stage(
            role,
            task_prompt,
            selection,
            config,
            attempt=attempt,
            on_progress=on_progress,
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
    # Only a load-bearing role blocking is a real failure. An advisory role
    # (validator/reviewer/security) that returns "BLOCKED" is confused, not a
    # dependency block, and must not mark the whole run failed.
    if subagent_blocked(result) and role in _LOAD_BEARING_ROLES:
        state.failed_phase = role.value
        state.error = result.output or result.error
    return result


def choose_coder_role(
    plan: SubAgentResult | None,
    research: SubAgentResult | None,
    *,
    user_prompt: str = "",
) -> AgentRole:
    """Choose an implementation role.

    The USER's request decides the primary deliverable; planner/researcher text
    only refines *which* implementer to use. A build/implement/complete/solve
    request is an implementation job even when it also needs tests or touches
    docs — so the test- and docs-only specialists are picked only when the user
    actually asked for tests or docs, judged from their own prompt. Otherwise
    route by the language signal in the prompt and evidence, defaulting to the
    generalist implementer (which can write any file) rather than a specialist
    that would write nothing.
    """
    prompt = (user_prompt or "").lower()
    evidence = _combined_output(plan, research).lower()

    if _TEST_REQUEST_RE.search(prompt):
        return AgentRole.TEST_CODER
    if _DOCS_REQUEST_RE.search(prompt):
        return AgentRole.DOCS_CODER

    combined = f"{prompt}\n{evidence}"
    if any(marker in combined for marker in _FRONTEND_EVIDENCE):
        return AgentRole.FRONTEND_CODER
    if any(marker in combined for marker in _PYTHON_EVIDENCE):
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
    return _contains_marker(evidence, _READ_ONLY_TASK_MARKERS) and _contains_marker(
        evidence, _DOCUMENT_TASK_MARKERS
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
    text = "\n\n".join([run.user_prompt] + [result.output for result in run.results]).lower()
    return any(marker in text for marker in _SECURITY_REVIEW_MARKERS)


def _build_planner_prompt(user_prompt: str) -> str:
    """Build the planner subagent's task prompt for ``user_prompt``."""
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
    """Build the researcher subagent's task prompt, embedding the planner's plan."""
    plan_text = plan.output if plan else "No explicit plan was produced for this task."
    return (
        "Follow the planner's execution plan. Only perform the research/context "
        "gathering assigned to the researcher role. Do not take over coding, "
        "validation, or review responsibilities, and do not modify files.\n\n"
        "Your report is the ONLY context the implementer receives — it cannot see "
        "your tool results, only what you write. So when the task refers to "
        "specific content (a document, an exercise, a section, a function), quote "
        "the exact relevant text VERBATIM in your report. Do not just summarize "
        "it or say where it is. If you read a document to find instructions, "
        "include those instructions in full.\n"
        "NEVER write a section heading and leave it empty (e.g. a title with no "
        "text under it). Paste the full content you read; if you genuinely could "
        "not obtain a piece of content, say so explicitly instead of leaving a "
        "blank placeholder.\n\n"
        "Report:\n"
        "- which planner-assigned researcher tasks you completed\n"
        "- the verbatim content the implementer will need (quoted in full)\n"
        "- relevant files, APIs, constraints, and risks\n"
        "- any missing dependency as `BLOCKED:` if the plan cannot continue\n\n"
        f"User task:\n{user_prompt}\n\nPlan:\n{plan_text}"
    )


def _build_implementation_prompt(
    user_prompt: str,
    plan: SubAgentResult | None,
    research: SubAgentResult | None,
) -> str:
    """Build the implementer subagent's task prompt from the plan and research findings."""
    # A document task runs no planner, so `plan` may be absent — fall back to the
    # user task directly rather than failing.
    plan_text = (
        plan.output
        if plan is not None
        else ("No separate plan was produced; follow the user task directly.")
    )
    research_text = (
        research.output if research is not None else ("No research output was produced.")
    )
    return (
        "Follow the execution plan and the researcher findings. "
        "Implement only the tasks assigned to your implementer role. Do not "
        "take over validation, review, security review, or unrelated role "
        "responsibilities. Do not touch files or areas outside the stated "
        "boundaries unless the research context proves they are required; if "
        "that happens, explain why.\n\n"
        "If the research findings do not include a specific detail you need "
        "(the exact instructions, the exact text of a document, the contents of "
        "a file), READ THE SOURCE DIRECTLY with your read tools before "
        "implementing — you have read_document and read_file. Never write a "
        "placeholder or a 'not found' stub when the source is available to read; "
        "read it and use the real content.\n\n"
        "Only return `BLOCKED:` with the exact missing dependency if the source "
        "genuinely cannot be read or does not exist — not merely because the "
        "research summary was thin.\n\n"
        "Your deliverable is the actual file(s) the task requires, WRITTEN TO "
        "DISK with their real content — not a description and not empty code "
        "blocks. Create every file the task calls for (the program/solution it "
        "asks you to build, and any tests it explicitly requests), and do not "
        "claim the task is complete until those files exist with real content.\n\n"
        f"User task:\n{user_prompt}\n\nPlan:\n{plan_text}\n\n"
        f"Research:\n{research_text}"
    )


def _build_validation_prompt(
    user_prompt: str,
    plan: SubAgentResult,
    research: SubAgentResult,
    implementation: SubAgentResult,
) -> str:
    """Build the validator subagent's task prompt from the plan, research, and implementation."""
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
    """Build the repair prompt that asks the implementer to fix a validation failure."""
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
    """Build the reviewer subagent's prompt from the full run's accumulated evidence."""
    evidence = "\n\n".join(
        f"[{result.role.value} attempt {result.attempt}]\n{result.output}" for result in run.results
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
    """Build the security reviewer subagent's prompt from the run's accumulated evidence."""
    evidence = "\n\n".join(
        f"[{result.role.value} attempt {result.attempt}]\n{result.output}" for result in run.results
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
    # Only a blocked load-bearing role (researcher or coder) makes the run
    # blocked. The planner, validator, reviewer, and security reviewer are
    # advisory: a confused "BLOCKED" from any of them must not discard the real
    # work the researcher and coder produced.
    blocked = next(
        (
            result
            for result in run.results
            if subagent_blocked(result) and result.role in _LOAD_BEARING_ROLES
        ),
        None,
    )
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
    coder = run.selected_coder_role.value if run.selected_coder_role else "none (read-only task)"
    review_text = reviewer.output if reviewer else "No reviewer output was produced."
    security_text = f"\n\nSecurity review:\n{security_reviewer.output}" if security_reviewer else ""
    validation_text = (
        last_validation.output if last_validation else "No validation output was produced."
    )
    if run.selected_coder_role is None:
        research_text = research.output if research else "No research output was produced."
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


# --- grounded paper-review flow -------------------------------------------


def _paper_review_phases() -> list[str]:
    """Return the ordered phase names of the grounded paper-review pipeline."""
    return (
        [AgentRole.INTAKE_REVIEWER.value]
        + [role.value for role in _PAPER_REVIEW_LENSES]
        + [AgentRole.GROUNDEDNESS_VERIFIER.value, AgentRole.REVISION_PLANNER.value]
    )


def _safe_execute(
    state: MultiAgentRun,
    role: AgentRole,
    task_prompt: str,
    selection: ModelSelection,
    config: AgentConfig,
    *,
    attempt: int = 1,
    on_progress: Callable[[str], None] | None = None,
) -> SubAgentResult | None:
    """Run a review phase resiliently: one failing lens never aborts the review."""
    try:
        result = _execute_phase(
            state,
            role,
            task_prompt,
            selection,
            config,
            attempt=attempt,
            on_progress=on_progress,
        )
    except Exception:
        state.failed_phase = None
        state.error = None
        return state.results[-1] if state.results else None
    if subagent_blocked(result):
        state.failed_phase = None
        state.error = None
    return result


def _absorb_fetched(ctx: ReviewContext, result: SubAgentResult | None) -> None:
    """Merge a subagent's web_fetch attempts into the review context.

    A prior successful fetch of a URL is never downgraded by a later failure.
    """
    if result is None or not result.tool_calls:
        return
    for url, info in extract_fetch_attempts(result.tool_calls).items():
        existing = ctx.fetch_attempts.get(url)
        if existing and existing.get("ok"):
            continue
        ctx.fetch_attempts[url] = info


def _verify_lens_output(
    state: MultiAgentRun,
    role: AgentRole,
    result: SubAgentResult | None,
    ctx: ReviewContext,
    selection: ModelSelection,
    config: AgentConfig,
    on_progress: Callable[[str], None] | None,
    *,
    chunk_text: str | None = None,
    part_label: str = "",
) -> VerificationBuckets:
    """Parse, deterministically verify, and re-ground a lens's findings once."""
    if result is None or not result.output:
        return VerificationBuckets()
    findings = parse_findings(result.output, default_lens=role.value)
    buckets = verify_findings(findings, ctx.index, ctx.fetch_attempts)

    to_reground = regroundable(buckets.quarantined)
    if to_reground:
        regrounded = _safe_execute(
            state,
            role,
            build_reground_prompt(ctx, to_reground, chunk_text=chunk_text, part_label=part_label),
            selection,
            config,
            attempt=2,
            on_progress=on_progress,
        )
        _absorb_fetched(ctx, regrounded)
        if regrounded is not None and regrounded.output:
            rg_findings = parse_findings(regrounded.output, default_lens=role.value)
            rg = verify_findings(rg_findings, ctx.index, ctx.fetch_attempts)
            reground_ids = {id(item) for item in to_reground}
            buckets.quarantined = [q for q in buckets.quarantined if id(q) not in reground_ids]
            buckets.merge(rg)
    return buckets


def _loads_any(text: str) -> list:
    """Parse JSON into a list of verdict objects, tolerating wrappers and single objects."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("verdicts", "results", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return []


def _parse_support_verdicts(text: str) -> dict[int, bool]:
    """Parse the groundedness verifier's output into ``{finding_index: supported}``."""
    text = text or ""
    objects: list = []
    for block in re.findall(r"```(?:json)?\s*(.*?)```", text, re.S):
        objects.extend(_loads_any(block.strip()))
    if not objects:
        objects.extend(_loads_any(text.strip()))
    if not objects:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            objects.extend(_loads_any(text[start : end + 1]))

    verdicts: dict[int, bool] = {}
    for obj in objects:
        if not isinstance(obj, dict) or "index" not in obj:
            continue
        try:
            index = int(obj["index"])
        except (TypeError, ValueError):
            continue
        supported = obj.get("supported")
        if isinstance(supported, bool):
            verdicts[index] = supported
        else:
            verdicts[index] = str(supported).strip().lower() in {
                "true",
                "yes",
                "y",
                "1",
                "supported",
            }
    return verdicts


def _groundedness_pass(
    state: MultiAgentRun,
    verified: list[Finding],
    ctx: ReviewContext,
    selection: ModelSelection,
    config: AgentConfig,
    on_progress: Callable[[str], None] | None,
) -> tuple[list[Finding], list[Finding]]:
    """Adversarial check that each verified quote actually supports its claim."""
    if not verified:
        return verified, []
    result = _safe_execute(
        state,
        AgentRole.GROUNDEDNESS_VERIFIER,
        build_groundedness_prompt(ctx, verified),
        selection,
        config,
        on_progress=on_progress,
    )
    if result is None or not result.output:
        # No verdict available: keep the code-verified findings (quotes do exist).
        return verified, []
    verdicts = _parse_support_verdicts(result.output)
    if not verdicts:
        return verified, []
    kept: list[Finding] = []
    dropped: list[Finding] = []
    for index, finding in enumerate(verified):
        if verdicts.get(index, True):
            kept.append(finding)
        else:
            finding.status = "quarantined"
            finding.reason = "Groundedness verifier: the quote does not support the claim."
            dropped.append(finding)
    return kept, dropped


def _run_paper_review(
    state: MultiAgentRun,
    selection: ModelSelection,
    config: AgentConfig,
    ctx: ReviewContext | None,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Run the grounded peer-review pipeline and return the assembled report."""
    if ctx is None or not ctx.readable:
        return REFUSAL_MESSAGE

    model_name = selection.display_name or selection.ollama_tag
    context_length = int(getattr(selection, "context_length", 0) or 0)

    # Pre-flight: never grab more than the model can take. If even one usable
    # chunk will not fit (or the paper would need too many chunks), abort and
    # recommend a larger-context model instead of producing an incomplete review.
    feasibility = assess_feasibility(ctx.index, context_length)
    if not feasibility.feasible:
        return infeasible_message(feasibility, model_name=model_name, context_length=context_length)

    chunks = plan_chunks(ctx.index.segments, feasibility.budget_chars)
    n_chunks = len(chunks)

    def part_label(i: int) -> str:
        return f"part {i + 1} of {n_chunks}" if n_chunks > 1 else ""

    buckets = VerificationBuckets()
    signals = QualitySignals()

    # Intake mapped over chunks; its diagnoses become shared context for lenses.
    intake_outputs: list[str] = []
    for i, chunk in enumerate(chunks):
        chunk_text = chunk_anchored_text(chunk)
        intake = _safe_execute(
            state,
            AgentRole.INTAKE_REVIEWER,
            build_intake_prompt(ctx, chunk_text=chunk_text, part_label=part_label(i)),
            selection,
            config,
            on_progress=on_progress,
        )
        signals.note_lens_run(intake.output if intake else "")
        _absorb_fetched(ctx, intake)
        buckets.merge(
            _verify_lens_output(
                state,
                AgentRole.INTAKE_REVIEWER,
                intake,
                ctx,
                selection,
                config,
                on_progress,
                chunk_text=chunk_text,
                part_label=part_label(i),
            )
        )
        if intake and intake.output:
            intake_outputs.append(intake.output)
    intake_text = "\n\n".join(intake_outputs)

    # Each lens mapped over each chunk: the window is never exceeded, and the
    # findings are merged across the whole manuscript (the divide-conquer phase).
    for role in _PAPER_REVIEW_LENSES:
        if role.value not in state.planned_phases:
            continue
        for i, chunk in enumerate(chunks):
            chunk_text = chunk_anchored_text(chunk)
            result = _safe_execute(
                state,
                role,
                build_lens_prompt(
                    role.value, ctx, intake_text, chunk_text=chunk_text, part_label=part_label(i)
                ),
                selection,
                config,
                on_progress=on_progress,
            )
            signals.note_lens_run(result.output if result else "")
            _absorb_fetched(ctx, result)
            buckets.merge(
                _verify_lens_output(
                    state,
                    role,
                    result,
                    ctx,
                    selection,
                    config,
                    on_progress,
                    chunk_text=chunk_text,
                    part_label=part_label(i),
                )
            )

    if AgentRole.GROUNDEDNESS_VERIFIER.value in state.planned_phases:
        kept, dropped = _groundedness_pass(
            state, buckets.verified, ctx, selection, config, on_progress
        )
        buckets.verified = kept
        buckets.quarantined.extend(dropped)

    planner_output = ""
    if AgentRole.REVISION_PLANNER.value in state.planned_phases:
        planner = _safe_execute(
            state,
            AgentRole.REVISION_PLANNER,
            build_revision_plan_prompt(ctx, buckets.verified),
            selection,
            config,
            on_progress=on_progress,
        )
        planner_output = planner.output if planner else ""

    # Post-flight quality gate: if the model could not actually do the job, drop
    # the result and recommend a stronger model rather than ship rubbish.
    _fill_quality_signals(signals, buckets, planner_output)
    ok, reason = assess_quality(signals)
    if not ok:
        return quality_abort_message(
            reason,
            model_name=model_name,
            recommended_min_context=recommended_context_for(total_manuscript_chars(ctx.index)),
        )

    return assemble_report(
        ctx,
        planner_output,
        buckets.verified,
        buckets.needs_check,
        buckets.refuted,
        buckets.quarantined,
    )


def _fill_quality_signals(
    signals: QualitySignals, buckets: VerificationBuckets, planner_output: str
) -> None:
    """Populate ``signals`` from the verification buckets and planner output for the gate."""
    signals.verified = len(buckets.verified)
    signals.needs_check = len(buckets.needs_check)
    signals.refuted = len(buckets.refuted)
    all_findings = buckets.verified + buckets.needs_check + buckets.refuted + buckets.quarantined
    for finding in all_findings:
        if finding.evidence_type == "manuscript":
            signals.manuscript_findings += 1
    for finding in buckets.quarantined:
        if finding.evidence_type == "manuscript" and "not found" in finding.reason.lower():
            signals.hallucinated += 1
    signals.planner_report_ok = bool(
        planner_output and "PAPER REVIEW REPORT" in planner_output.upper()
    )


def run_multi_agent(
    user_prompt: str,
    selection: ModelSelection,
    *,
    config: AgentConfig | None = None,
    max_repair_attempts: int = 2,
    on_progress: Callable[[str], None] | None = None,
    review_context: ReviewContext | None = None,
) -> str:
    """Run the sequential multi-agent flow (code tasks or grounded paper review)."""
    cfg = config or AgentConfig(cwd=".")
    state = MultiAgentRun(user_prompt=user_prompt)

    # Deterministic pre-orchestration intent gate (NVIDIA-style intent routing).
    # Decide which phases are allowed *before* building or executing any phase.
    decision = classify_multiagent_intent(user_prompt)
    is_paper_review = (
        cfg.multiagent_flow == "paper_review" or decision.intent == MultiAgentIntent.PAPER_REVIEW
    )
    if is_paper_review:
        planned_phases = _paper_review_phases()
        state.intent = MultiAgentIntent.PAPER_REVIEW.value
        state.requires_write = False
        state.intent_reason = (
            decision.reason
            if decision.intent == MultiAgentIntent.PAPER_REVIEW
            else "Paper-review flow selected explicitly."
        )
        state.intent_confidence = "high"
    else:
        planned_phases = list(decision.allowed_phases)
        state.intent = decision.intent.value
        state.requires_write = decision.requires_write
        state.intent_reason = decision.reason
        state.intent_confidence = decision.confidence
    state.planned_phases = planned_phases
    if on_progress:
        on_progress("Preparing the multi-agent workflow...")
    else:
        console.print(
            f"[cyan][multi-agent][/cyan] intent={state.intent} "
            f"requires_write={state.requires_write} phases={planned_phases}"
        )

    started_at = datetime.now(UTC)
    run_log = RunLogger.maybe_create(cfg, selection, user_prompt)
    if run_log:
        run_log.start()

    final_status = "success"
    try:
        if is_paper_review:
            state.final_answer = _run_paper_review(
                state, selection, cfg, review_context, on_progress=on_progress
            )
            return state.final_answer

        plan: SubAgentResult | None = None
        if "planner" in planned_phases:
            plan_prompt = _build_planner_prompt(user_prompt)
            plan = _execute_phase(
                state,
                AgentRole.PLANNER,
                plan_prompt,
                selection,
                cfg,
                on_progress=on_progress,
            )
            if subagent_blocked(plan):
                # The planner is advisory and has no tools; a weak model may flail
                # trying to act and burn its round cap. That must NOT abort the run
                # — the researcher (read tools) and coder (write tools) do the real
                # work. Keep the partial plan and continue.
                if on_progress is None:
                    console.print(
                        "[yellow][multi-agent][/yellow] planner did not finish "
                        "cleanly; continuing with the available plan."
                    )
                plan.status = "partial"
                state.failed_phase = None
                state.error = None

        research: SubAgentResult | None = None
        if "researcher" in planned_phases:
            research_prompt = _build_research_prompt(user_prompt, plan)
            research = _execute_phase(
                state,
                AgentRole.RESEARCHER,
                research_prompt,
                selection,
                cfg,
                on_progress=on_progress,
            )
            if subagent_blocked(research):
                state.final_answer = synthesize_final_answer(state)
                return state.final_answer

        # Implementation + validation only run when the intent allows writes.
        if "coder" in planned_phases:
            coder_role = choose_coder_role(plan, research, user_prompt=user_prompt)
            state.selected_coder_role = coder_role

            implementation_prompt = _build_implementation_prompt(user_prompt, plan, research)
            implementation = _execute_phase(
                state,
                coder_role,
                implementation_prompt,
                selection,
                cfg,
                on_progress=on_progress,
            )
            if subagent_blocked(implementation):
                state.final_answer = synthesize_final_answer(state)
                return state.final_answer

            if "validator" in planned_phases:
                # Every planned flow that includes "validator" also includes
                # "planner" and "researcher", so those phases have already run
                # here and produced their results.
                assert plan is not None
                assert research is not None
                validation_prompt = _build_validation_prompt(
                    user_prompt, plan, research, implementation
                )
                validation = _execute_phase(
                    state,
                    AgentRole.VALIDATOR,
                    validation_prompt,
                    selection,
                    cfg,
                    on_progress=on_progress,
                )
                # A blocked/confused validator is advisory — keep the run going
                # to the reviewer and final synthesis instead of discarding the
                # implementation. Only a genuine validation *failure* (below)
                # triggers the repair loop.

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
                        on_progress=on_progress,
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
                        on_progress=on_progress,
                    )
                    if subagent_blocked(validation):
                        # Validator gave up mid-repair: stop retrying, but still
                        # review and synthesize what the coder produced.
                        break

        if "reviewer" in planned_phases:
            review_prompt = _build_review_prompt(state)
            review = _execute_phase(
                state,
                AgentRole.REVIEWER,
                review_prompt,
                selection,
                cfg,
                on_progress=on_progress,
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
                    on_progress=on_progress,
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
        if on_progress:
            on_progress("")
        ended_at = datetime.now(UTC)
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
