"""Sequential multi-agent orchestrator.

This module is intentionally not wired into the default harness flow yet. The
classic `run_agent` path remains unchanged until the multi-agent route is
explicitly enabled by a later CLI/config integration.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Callable

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
    "no pasa",
    "fallo",
    "falla",
    "falló",
    "fallida",
    "fallido",
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

# A validator that cannot find real tool evidence must always be treated as a
# failure, even if it happens to echo a success token (e.g. the literal content
# `MULTIAGENTE_OK`, whose `ok` substring used to be mis-read as a pass). These
# markers dominate the success/failure markers below.
_INSUFFICIENT_EVIDENCE_MARKERS = (
    "insufficient evidence",
    "insufficient tool evidence",
    "missing evidence",
    "no evidence",
    "evidencia insuficiente",
    "insuficiente evidencia",
    "falta de evidencia",
    "sin evidencia",
    "no hay evidencia",
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

_WRITE_EVIDENCE_TOOLS = frozenset({
    "write_file",
    "edit_file",
    "apply_patch",
    "write_docx",
    "docx_to_pdf",
    "pdf_to_docx",
    "notebook_edit",
})

_READBACK_EVIDENCE_TOOLS = frozenset({
    "read_file",
    "read_document",
    "grep",
    "inspect_file",
})

_CHANGE_SCOPE_EVIDENCE_TOOLS = frozenset({
    "git_status",
    "git_diff",
})


def _combined_output(*results: SubAgentResult | None) -> str:
    return "\n\n".join(
        result.output for result in results if result is not None and result.output
    )


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", text)
        for marker in markers
    )


def _tool_name(entry: dict[str, object]) -> str:
    return str(entry.get("tool") or "")


def _tool_ok(entry: dict[str, object]) -> bool:
    return bool(entry.get("ok"))


def _tool_args(entry: dict[str, object]) -> dict[str, object]:
    args = entry.get("arguments")
    return args if isinstance(args, dict) else {}


def _tool_target(entry: dict[str, object]) -> str:
    args = _tool_args(entry)
    for key in ("path", "source", "output", "file", "target"):
        value = args.get(key)
        if value:
            return str(value)
    return "(target unknown)"


def _tool_output_preview(entry: dict[str, object], *, limit: int = 180) -> str:
    preview = str(entry.get("output_preview") or entry.get("output") or "")
    preview = " ".join(preview.split())
    if len(preview) > limit:
        return preview[:limit] + "... (truncated)"
    return preview


def _evidence_entries(results: list[SubAgentResult]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for result in results:
        for entry in result.tool_calls:
            enriched = dict(entry)
            enriched["role"] = result.role.value
            entries.append(enriched)
    return entries


def _is_change_scope_evidence(entry: dict[str, object]) -> bool:
    name = _tool_name(entry)
    if name in _CHANGE_SCOPE_EVIDENCE_TOOLS:
        return True
    if name != "bash":
        return False
    command = str(_tool_args(entry).get("command") or "").lower()
    return "git status" in command or "git diff" in command


def _format_evidence_list(entries: list[dict[str, object]]) -> str:
    if not entries:
        return "none"
    lines = []
    for entry in entries:
        role = str(entry.get("role") or "unknown")
        name = _tool_name(entry)
        target = _tool_target(entry)
        preview = _tool_output_preview(entry)
        suffix = f"; output preview: {preview}" if preview else ""
        lines.append(f"- {role}: {name}({target}){suffix}")
    return "\n".join(lines)


def _build_tool_evidence_report(
    user_prompt: str,
    results: list[SubAgentResult],
    *,
    selected_coder_role: AgentRole | None,
) -> str:
    entries = [entry for entry in _evidence_entries(results) if _tool_ok(entry)]
    writes = [entry for entry in entries if _tool_name(entry) in _WRITE_EVIDENCE_TOOLS]
    readbacks = [
        entry for entry in entries if _tool_name(entry) in _READBACK_EVIDENCE_TOOLS
    ]
    scope_checks = [entry for entry in entries if _is_change_scope_evidence(entry)]
    implementer = (
        selected_coder_role.value
        if selected_coder_role is not None
        else "none selected"
    )
    return (
        "Real tool-call evidence available. Treat this section as the only "
        "source of truth for filesystem effects; do not treat subagent narrative "
        "text as proof.\n"
        f"- User task: {user_prompt}\n"
        f"- Selected implementer: {implementer}\n"
        "- Filesystem write evidence:\n"
        f"{_format_evidence_list(writes)}\n"
        "- Readback/content evidence:\n"
        f"{_format_evidence_list(readbacks)}\n"
        "- Change-scope evidence (git status/diff or equivalent):\n"
        f"{_format_evidence_list(scope_checks)}"
    )


def _evidence_rules() -> str:
    return (
        "Evidence rules:\n"
        "- You may say a file was created or modified only when the evidence "
        "section includes a successful real write tool result.\n"
        "- You may say content is correct only when the evidence section includes "
        "a successful readback/content tool result showing that content.\n"
        "- You may say no other files changed only when the evidence section "
        "includes git status/git diff or equivalent change-scope evidence.\n"
        "- If evidence is missing, say `insufficient evidence` and name the "
        "missing evidence instead of claiming success.\n"
        "- Run evidence may contain unsupported subagent narrative. Do not "
        "repeat those claims unless the real tool-call evidence supports them.\n"
        "- Do not invent or mention non-existent verification helpers; use only "
        "actual tool names present in evidence."
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
    last_validation = run.latest_for(AgentRole.VALIDATOR)
    if failed_phase is None:
        if last_validation and validation_failed(last_validation):
            failed_phase = AgentRole.VALIDATOR.value
        elif write_task_lacks_evidence(run) and run.selected_coder_role is not None:
            # No write-tool evidence: the missing effect is the implementer's.
            failed_phase = run.selected_coder_role.value
    trace_status = "failed" if run.error else final_run_status(run)
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
    label = _role_label(role, attempt)
    progress_label = _role_progress_label(role, attempt)
    if on_progress:
        on_progress(progress_label)
    else:
        console.print(f"[cyan][multi-agent][/cyan] {progress_label}...")
    try:
        kwargs = {"attempt": attempt}
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
    if subagent_blocked(result):
        state.failed_phase = role.value
        state.error = result.output or result.error
    return result


def choose_coder_role(
    plan: SubAgentResult | None, research: SubAgentResult | None
) -> AgentRole:
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
    """Best-effort validation classifier for the first sequential version.

    Matching is word-boundary aware (via :func:`_contains_marker`) so a success
    token can no longer be matched as a substring of unrelated text — the bug
    where the literal content ``MULTIAGENTE_OK`` made ``ok`` look like a pass.

    A validator that reports *insufficient evidence* always counts as a failure
    and dominates any success token it may also echo, because a write task
    cannot be confirmed without real tool-call evidence.
    """
    output = validation.output.lower()
    if _contains_marker(output, _INSUFFICIENT_EVIDENCE_MARKERS):
        return True
    has_success = _contains_marker(output, _VALIDATION_SUCCESS_MARKERS)
    has_failure = _contains_marker(output, _VALIDATION_FAILURE_MARKERS)
    if has_success and not has_failure:
        return False
    return has_failure


def has_write_tool_evidence(results: list[SubAgentResult]) -> bool:
    """True only when a successful real write/edit tool call was recorded.

    This is the single source of truth for "a file was actually created or
    modified". Subagent narrative text (including a returned Python script that
    *describes* an ``open(..., "w")``) never counts — only a logged
    ``ToolResult`` from a real write tool does.
    """
    return any(
        _tool_ok(entry) and _tool_name(entry) in _WRITE_EVIDENCE_TOOLS
        for entry in _evidence_entries(results)
    )


# Self-executing "solution" smells: a coder that returns code which performs the
# filesystem effect itself (instead of calling a traceable write tool) bypasses
# the evidence/permission channel entirely. These patterns flag that anti-pattern
# so the orchestrator can name it instead of silently passing.
_UNTRACEABLE_FS_MUTATION_RE = re.compile(
    r"""
      \bopen\s*\([^)]*['"][rbt]*[wax][rbt+]*['"]   # open(path, "w"/"a"/"x"/"wb"...)
    | \.write_text\s*\(
    | \.write_bytes\s*\(
    | \bos\.remove\s*\(
    | \bos\.unlink\s*\(
    | \bshutil\.(?:rmtree|move|copy)\s*\(
    """,
    re.IGNORECASE | re.VERBOSE,
)


def looks_like_untraceable_fs_mutation(text: str) -> bool:
    """Detect a returned code blob that mutates the filesystem outside tools."""
    return bool(_UNTRACEABLE_FS_MUTATION_RE.search(text or ""))


def write_task_lacks_evidence(run: MultiAgentRun) -> bool:
    """A write task that produced no real write-tool evidence is not a success.

    The deterministic guard behind requirement: the orchestrator must never
    report a clean ``completed`` status for a write task whose effects were
    never proven by a logged write ``ToolResult``.
    """
    if not run.requires_write or run.selected_coder_role is None:
        return False
    return not has_write_tool_evidence(run.results)


def final_run_status(run: MultiAgentRun) -> str:
    """Compute the authoritative run status from evidence, not narrative.

    Priority: a failing/insufficient validator dominates; otherwise a write task
    with no real write-tool evidence is downgraded to ``insufficient_evidence``;
    only then is the run a clean ``completed``.
    """
    last_validation = run.latest_for(AgentRole.VALIDATOR)
    if last_validation and validation_failed(last_validation):
        return "validation_failed"
    if write_task_lacks_evidence(run):
        return "insufficient_evidence"
    return "completed"


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
        "Your report is the ONLY context the implementer receives — it cannot see "
        "your tool results, only what you write. So when the task refers to "
        "specific content (a document, an exercise, a section, a function), quote "
        "the exact relevant text VERBATIM in your report. Do not just summarize "
        "it or say where it is. If you read a document to find instructions, "
        "include those instructions in full.\n\n"
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
    # A document task runs no planner, so `plan` may be absent — fall back to the
    # user task directly rather than failing.
    plan_text = plan.output if plan is not None else (
        "No separate plan was produced; follow the user task directly."
    )
    research_text = research.output if research is not None else (
        "No research output was produced."
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
        "Apply every filesystem change through your real tools: use `write_file` "
        "to create or overwrite a file and `edit_file`/`apply_patch` to modify "
        "one. Do NOT answer with a Python (or shell) script that performs the "
        "change itself — for example returning code that calls "
        '`open(path, "w")`. Code returned as text is never executed, leaves no '
        "tool evidence, and will be treated as no change at all. After writing, "
        "read the file back with `read_file` so the content can be verified.\n\n"
        f"User task:\n{user_prompt}\n\nPlan:\n{plan_text}\n\n"
        f"Research:\n{research_text}"
    )


def _build_validation_prompt(
    user_prompt: str,
    plan: SubAgentResult,
    research: SubAgentResult,
    implementation: SubAgentResult,
) -> str:
    evidence = _build_tool_evidence_report(
        user_prompt,
        [implementation],
        selected_coder_role=implementation.role,
    )
    return (
        "Follow the planner's validation expectations. Validate only the "
        "implemented work against the plan, research findings, and success "
        "criteria. Run focused tests or checks when possible. Clearly state "
        "whether validation passed or failed, and include actionable failure "
        "details tied to the plan.\n\n"
        "If the implementation did not follow the plan, report validation as "
        "failed and explain the mismatch.\n\n"
        f"{_evidence_rules()}\n\n"
        f"{evidence}\n\n"
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
        "If the validation failed for lack of evidence, the most likely cause is "
        "that the previous attempt described or returned code instead of calling "
        "a tool. Make the change with `write_file`/`edit_file`/`apply_patch` and "
        "read it back with `read_file`; never return a script that calls "
        '`open(path, "w")` as the solution.\n\n'
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
    tool_evidence = _build_tool_evidence_report(
        run.user_prompt,
        run.results,
        selected_coder_role=run.selected_coder_role,
    )
    return (
        "Review the completed multi-agent run against the planner's execution "
        "plan. Check whether each subagent stayed within its assigned task, "
        "respected dependencies, avoided overlapping responsibilities, and met "
        "the success criteria. Identify remaining risks, missing tests, "
        "regressions, or incomplete requirements. Do not modify files.\n\n"
        f"{_evidence_rules()}\n\n"
        f"{tool_evidence}\n\n"
        f"User task:\n{run.user_prompt}\n\nRun evidence:\n{evidence}"
    )


def _build_security_review_prompt(run: MultiAgentRun) -> str:
    evidence = "\n\n".join(
        f"[{result.role.value} attempt {result.attempt}]\n{result.output}"
        for result in run.results
    )
    tool_evidence = _build_tool_evidence_report(
        run.user_prompt,
        run.results,
        selected_coder_role=run.selected_coder_role,
    )
    return (
        "Review the completed multi-agent run specifically for security and "
        "permission risks, using the planner's boundaries as the source of "
        "truth. Check command execution, filesystem writes, secret handling, "
        "approval behavior, path safety, and whether any role exceeded its "
        "assigned scope. Do not modify files.\n\n"
        f"{_evidence_rules()}\n\n"
        "If no implementer was selected, do not state that an implementer "
        "created, modified, or wrote files. If there is no real write-tool "
        "evidence, say there is insufficient evidence of filesystem writes.\n\n"
        f"{tool_evidence}\n\n"
        f"User task:\n{run.user_prompt}\n\nRun evidence:\n{evidence}"
    )


def synthesize_final_answer(run: MultiAgentRun) -> str:
    """Create a concise final answer from orchestrator state."""
    # A blocked planner is not fatal — it is advisory and the load-bearing roles
    # (researcher, coder) run after it — so it must not mark the whole run blocked.
    blocked = next(
        (
            result
            for result in run.results
            if subagent_blocked(result) and result.role != AgentRole.PLANNER
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
    status = final_run_status(run)
    coder = (
        run.selected_coder_role.value
        if run.selected_coder_role
        else "none (read-only task)"
    )
    evidence_note = ""
    if status == "insufficient_evidence":
        evidence_note = (
            "\n\nEvidence gate: this was a write task but no successful "
            "write_file/edit_file tool result was recorded, so the change "
            "cannot be confirmed."
        )
        if any(
            looks_like_untraceable_fs_mutation(result.output)
            for result in run.results
            if result.role == run.selected_coder_role
        ):
            evidence_note += (
                " The implementer returned code that performs the file "
                "operation itself instead of calling write_file/edit_file; "
                "such code is not executed through the traceable tool channel."
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
        f"{evidence_note}"
    )


def run_multi_agent(
    user_prompt: str,
    selection: ModelSelection,
    *,
    config: AgentConfig | None = None,
    max_repair_attempts: int = 2,
    on_progress: Callable[[str], None] | None = None,
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
    if on_progress:
        on_progress("Preparing the multi-agent workflow...")
    else:
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
            coder_role = choose_coder_role(plan, research)
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
