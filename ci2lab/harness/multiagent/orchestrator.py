"""Sequential multi-agent orchestrator.

This module is intentionally not wired into the default harness flow yet. The
classic `run_agent` path remains unchanged until the multi-agent route is
explicitly enabled by a later CLI/config integration.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
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
from ci2lab.harness.run_logger import RunLogger
from ci2lab.harness.tools.executor_parts.core import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall


@dataclass(frozen=True)
class ValidationContract:
    """Compact validation spec passed to the validator instead of long context."""

    task_type: str
    expected_artifacts: list[str] = field(default_factory=list)
    expected_contents_or_properties: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    required_evidence_tools: list[str] = field(default_factory=list)
    expected_changed_paths: list[str] = field(default_factory=list)
    forbidden_changed_paths: list[str] = field(default_factory=list)
    scope_check_required: bool = False
    test_commands: list[str] = field(default_factory=list)
    baseline_summary: str = "Pre-run git baseline: clean or unavailable."
    implementation_evidence_summary: str = "No implementation tool evidence recorded."


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
    "fail",
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

_NON_ACTIONABLE_VALIDATION_FAILURE_MARKERS = (
    *_INSUFFICIENT_EVIDENCE_MARKERS,
    "missing successful tool evidence",
    "role_violation",
    "invalid_tool_via_bash",
    "forbidden tool",
    "hallucinated_output",
    "ungrounded_claims",
    "blocked_by_skill",
    "todo_write",
    "missing git_status",
    "missing git_diff",
    "validator did not run git_status",
    "validator did not run git_diff",
    "do not report pass",
)

_ACTIONABLE_IMPLEMENTATION_FAILURE_MARKERS = (
    "file missing",
    "missing file",
    "file does not exist",
    "not found",
    "content incorrect",
    "incorrect content",
    "wrong content",
    "contenido incorrecto",
    "expected content",
    "expected:",
    "actual:",
    "got:",
    "test failed",
    "tests failed",
    "pytest failed",
    "unexpected change",
    "unexpected file",
    "modified outside",
    "outside scope",
    "implementation mismatch",
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

# Implementation language a researcher may surface when a "read this document"
# task actually requires writing code (e.g. an exercise statement in a PDF).
_RESEARCH_DISCOVERED_WRITE_MARKERS = (
    "task involves implementing",
    "involves implementing",
    "implementing a program",
    "implement a program",
    "program in python",
    "python program",
    "write a program",
    "create a program",
    "modify files",
    "write files",
    "create files",
    "execute the task",
    "carry out the task",
    "perform the exercise",
    "complete the exercise",
)

_CODE_CONSTRAINT_MARKERS = (
    "no use of",
    "do not use",
    "only use",
    "append method",
    "`append`",
    "`in` operator",
    "operator `in`",
)

_WRITE_EVIDENCE_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "apply_patch",
        "write_docx",
        "docx_to_pdf",
        "pdf_to_docx",
        "notebook_edit",
    }
)

_READBACK_EVIDENCE_TOOLS = frozenset(
    {
        "read_file",
        "read_document",
        "grep",
        "inspect_file",
    }
)
_FILE_CONTENT_CONTRACT_FILE_RE = re.compile(
    r"\b(?:create|crea|crear)\b[\s\S]{0,120}?"
    r"\b(?:file|archivo|fichero)\s+(?:named|called|llamado|llamada)\s+"
    r"[`\"']?([A-Za-z0-9_./\\-]+)[`\"']?",
    re.IGNORECASE,
)
_FILE_CONTENT_CONTRACT_CONTENT_RE = re.compile(
    r"(?:with\s+exactly\s+(?:this\s+)?content|"
    r"con\s+exactamente\s+este\s+contenido|"
    r"expected\s+exact\s+content|"
    r"contenido\s+exacto\s+esperado)"
    r"\s*:\s*(?:`([^`]+)`|\"([^\"]+)\"|'([^']+)'|([^\r\n.]+))",
    re.IGNORECASE,
)
_ONLY_MODIFY_PATH_RE = re.compile(
    r"\b(?:only\s+modify|solo\s+modifica)\s+[`\"']?([A-Za-z0-9_./\\-]+)[`\"']?",
    re.IGNORECASE,
)
_WORK_ONLY_FOLDER_RE = re.compile(
    r"\b(?:work\s+only\s+inside\s+folder|trabaja\s+dentro\s+de\s+la\s+carpeta)\s+"
    r"[`\"']?([A-Za-z0-9_./\\-]+)[`\"']?",
    re.IGNORECASE,
)
_NO_OTHER_FILE_RE = re.compile(
    r"\b(?:do\s+not\s+modify\s+any\s+other\s+file|"
    r"no\s+modifiques\s+ning(?:u|\u00fa)n\s+otro\s+archivo)\b",
    re.IGNORECASE,
)
_DIFF_PATH_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")

_CHANGE_SCOPE_EVIDENCE_TOOLS = frozenset(
    {
        "git_status",
        "git_diff",
    }
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

_CHANGE_SCOPE_REQUEST_MARKERS = (
    "git status",
    "git_status",
    "git diff",
    "git_diff",
    "diff final",
    "final diff",
    "review the diff",
    "revisa el diff",
    "scope",
    "alcance",
    "no modifiques ningún otro",
    "no modifiques ningun otro",
    "no cambies ningún otro",
    "no cambies ningun otro",
    "do not modify any other",
    "do not change any other",
    "no other files",
)


# Tools that read-only roles (validator, reviewer, security_reviewer) are
# never allowed to call. Attempting them is a role discipline violation.
_FORBIDDEN_TOOLS_FOR_ROLE: dict[AgentRole, frozenset[str]] = {
    AgentRole.VALIDATOR: frozenset(
        {
            "todo_write",
            "write_file",
            "edit_file",
            "apply_patch",
            "notebook_edit",
        }
    ),
    AgentRole.REVIEWER: frozenset(
        {
            "todo_write",
            "write_file",
            "edit_file",
            "apply_patch",
            "notebook_edit",
        }
    ),
    AgentRole.SECURITY_REVIEWER: frozenset(
        {
            "todo_write",
            "write_file",
            "edit_file",
            "apply_patch",
            "notebook_edit",
        }
    ),
    AgentRole.RESEARCHER: frozenset(
        {
            "write_file",
            "edit_file",
            "apply_patch",
            "notebook_edit",
        }
    ),
}

# Document-processing tool names whose appearance in a reviewer/security_reviewer
# output is suspicious when they are not present in the task or real tool calls.
_HALLUCINATED_DOC_TOOLS = frozenset(
    {
        "write_docx",
        "pdf_to_docx",
        "docx_to_pdf",
    }
)

# Matches "report.docx", "document.pdf", "document.docx" in output text.
_HALLUCINATED_DOC_FILE_RE = re.compile(
    r"\b(?:report|document)\s*\.\s*(?:docx|pdf)\b",
    re.IGNORECASE,
)

# Phrases that indicate a researcher is claiming filesystem effects without
# real tool-call evidence (presenting requirements as if they were done facts).
_RESEARCHER_FABRICATION_MARKERS = (
    "i created",
    "i wrote",
    "i verified",
    "i modified",
    "i confirmed the file",
    "the diff is empty",
    "the diff shows nothing",
    "diff vacío",
    "diff está vacío",
    "no git changes",
    "git status is clean",
    "creé el archivo",
    "verifiqué el archivo",
    "confirmé que",
)

_PROMPT_PATH_RE = re.compile(
    r"\b[\w./\\-]+\.(?:py|txt|md|json|yaml|yml|toml|ini|csv|html|css|js|ts|tsx|jsx)\b",
    re.IGNORECASE,
)
_PROMPT_EXACT_CONTENT_RE = re.compile(
    r"\b(?:exactly|exactamente|contenido)\s*(?:this content|este contenido)?\s*:?\s*"
    r"(?:`([^`]+)`|\"([^\"]+)\"|'([^']+)'|([A-Za-z0-9_.:-]+))",
    re.IGNORECASE,
)
_PYTEST_COMMAND_RE = re.compile(r"\bpytest\s+[^\n\r;|&]+", re.IGNORECASE)
_BASH_PSEUDO_TOOL_RE = re.compile(
    r"^\s*(?:git_status|git_diff|read_file|write_file|edit_file|apply_patch|todo_write)\b",
    re.IGNORECASE,
)


def _combined_output(*results: SubAgentResult | None) -> str:
    """Join the non-empty outputs of the given results with blank-line separators."""
    return "\n\n".join(result.output for result in results if result is not None and result.output)


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    """True if any marker appears in ``text`` as a whole word (word-boundary match)."""
    return any(re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", text) for marker in markers)


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


def _shorten(text: str, *, limit: int = 240) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit] + "... (truncated)"


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


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


def _detect_role_violation(result: SubAgentResult) -> SubAgentResult:
    """Mark a phase as role_violation when it attempted a forbidden tool.

    Both blocked (blocked_by_skill) and hypothetically successful forbidden
    tool calls are flagged so the orchestrator can name the violation instead
    of silently accepting a compromised phase output.
    """
    forbidden = _FORBIDDEN_TOOLS_FOR_ROLE.get(result.role, frozenset())
    if not forbidden:
        return result
    violations = [entry for entry in result.tool_calls if _tool_name(entry) in forbidden]
    if not violations:
        return result
    violation_names = sorted({_tool_name(e) for e in violations})
    detail = (
        f"role_violation: {result.role.value} attempted forbidden tool(s): "
        f"{', '.join(violation_names)}"
    )
    result.status = "role_violation"
    result.error = detail
    warning = (
        f"\n\n[ROLE_VIOLATION] {result.role.value} attempted forbidden tool(s): "
        f"{', '.join(violation_names)}. These tools are not permitted for this "
        "role. Subsequent independent checks in the same batch may have been "
        "disrupted."
    )
    result.output = (result.output.strip() + warning) if result.output.strip() else warning.strip()
    return result


def _detect_invalid_tool_via_bash(result: SubAgentResult) -> SubAgentResult:
    """Flag attempts to call dedicated tools by typing their names into bash."""
    if result.status == "completed" and result.output.startswith("PASS: required"):
        return result
    if result.role not in {
        AgentRole.VALIDATOR,
        AgentRole.REVIEWER,
        AgentRole.SECURITY_REVIEWER,
        AgentRole.RESEARCHER,
    }:
        return result
    invalid = []
    for entry in result.tool_calls:
        if _tool_name(entry) != "bash":
            continue
        command = str(_tool_args(entry).get("command") or "")
        if _BASH_PSEUDO_TOOL_RE.search(command):
            invalid.append(command)
    if not invalid:
        return result
    detail = (
        f"invalid_tool_via_bash: {result.role.value} attempted dedicated "
        f"tool(s) through bash: {', '.join(_shorten(cmd, limit=80) for cmd in invalid)}"
    )
    result.status = "invalid_tool_via_bash"
    result.error = detail
    warning = (
        f"\n\n[INVALID_TOOL_VIA_BASH] {result.role.value} attempted to invoke "
        "a dedicated tool name through `bash`. Use the dedicated tool call "
        "directly instead."
    )
    result.output = (result.output.strip() + warning) if result.output.strip() else warning.strip()
    return result


def _detect_researcher_unsupported_claims(result: SubAgentResult) -> SubAgentResult:
    """Flag researcher output that claims filesystem effects with no tool evidence.

    A researcher with zero tool calls cannot have created, verified, or seen
    a diff — it is presenting requirements as if they were proven facts.
    """
    if result.role != AgentRole.RESEARCHER:
        return result
    if result.tool_calls:
        return result
    output_lower = result.output.lower()
    if not any(marker in output_lower for marker in _RESEARCHER_FABRICATION_MARKERS):
        return result
    warning = (
        "\n\n[UNGROUNDED_CLAIMS] This researcher output makes action claims "
        "(e.g. created/verified/diff-empty) without any real tool-call evidence. "
        "These statements are unverified context, not proven facts. Downstream "
        "phases must not treat them as tool evidence."
    )
    result.output = result.output + warning
    return result


def _detect_hallucinated_output(
    result: SubAgentResult,
    run: MultiAgentRun,
) -> SubAgentResult:
    """Flag reviewer/security_reviewer output that mentions artifacts alien to the task.

    When the output references document tools or files (write_docx, pdf_to_docx,
    report.docx …) that are not in the user prompt and were never actually called
    during the run, the reviewer has drifted to a different task context.
    """
    if result.role not in {AgentRole.REVIEWER, AgentRole.SECURITY_REVIEWER}:
        return result
    output_lower = result.output.lower()
    prompt_lower = run.user_prompt.lower()
    real_tools = frozenset(_tool_name(e) for r in run.results for e in r.tool_calls if _tool_ok(e))
    alien_doc_tools = {
        t
        for t in _HALLUCINATED_DOC_TOOLS
        if t in output_lower and t not in prompt_lower and t not in real_tools
    }
    doc_files = _HALLUCINATED_DOC_FILE_RE.findall(result.output)
    alien_doc_files = {f.lower() for f in doc_files if f.lower() not in prompt_lower}
    aliens = sorted(alien_doc_tools | alien_doc_files)
    if not aliens:
        return result
    warning = (
        f"\n\n[HALLUCINATED_OUTPUT] This phase mentioned artifact(s)/tool(s) "
        f"({', '.join(aliens)}) that are not present in the task prompt or real "
        "tool-call evidence. This content likely describes a different task. "
        "It should not be used as the final answer or blocked reason."
    )
    result.status = "hallucinated_output"
    result.output = result.output + warning
    return result


def _apply_role_guardrails(result: SubAgentResult, run: MultiAgentRun) -> SubAgentResult:
    """Apply all role-discipline and evidence guardrails to a phase result."""
    result = _detect_role_violation(result)
    result = _detect_invalid_tool_via_bash(result)
    result = _detect_researcher_unsupported_claims(result)
    result = _detect_hallucinated_output(result, run)
    return result


def _capture_git_baseline(cwd: str) -> str | None:
    """Capture `git status --short` before the run to identify pre-existing WIP."""
    try:
        proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            out = proc.stdout.strip()
            return out if out else "(clean)"
        return None
    except Exception:
        return None


def _git_scope_tools_available(cwd: str) -> bool:
    """Return whether git status/diff can provide change-scope evidence in cwd."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def _git_baseline_section(baseline: str | None) -> str:
    """Return a prompt section describing pre-run WIP, or '' when baseline is clean."""
    if not baseline or baseline == "(clean)":
        return ""
    return (
        "Pre-run git baseline (WIP present BEFORE this run started — do NOT "
        "attribute these changes to the current run unless the run explicitly "
        "touched them):\n"
        f"{baseline}\n"
    )


def _build_tool_evidence_report(
    user_prompt: str,
    results: list[SubAgentResult],
    *,
    selected_coder_role: AgentRole | None,
) -> str:
    entries = [entry for entry in _evidence_entries(results) if _tool_ok(entry)]
    writes = [entry for entry in entries if _tool_name(entry) in _WRITE_EVIDENCE_TOOLS]
    readbacks = [entry for entry in entries if _tool_name(entry) in _READBACK_EVIDENCE_TOOLS]
    scope_checks = [entry for entry in entries if _is_change_scope_evidence(entry)]
    implementer = selected_coder_role.value if selected_coder_role is not None else "none selected"
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
    evidence_entries = [
        EvidenceEntry.from_tool_call(
            entry,
            role=result.role,
            phase=result.role,
            source_run=result.subagent_run_dir,
        ).to_dict()
        for entry in tool_calls
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
        "evidence_entries": evidence_entries,
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
        "git_baseline": run.git_baseline,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "contract_validation_schema_version": CONTRACT_VALIDATION_SCHEMA_VERSION,
        "contract_validation": (
            run.contract_validation.to_dict() if run.contract_validation else None
        ),
        "failure_classification_schema_version": FAILURE_CLASSIFICATION_SCHEMA_VERSION,
        "failure_classification": (
            run.failure_classification.to_dict() if run.failure_classification else None
        ),
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


def _read_json_file(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl_file(path: Path) -> list[dict[str, object]]:
    try:
        return [
            item
            for item in (
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            if isinstance(item, dict)
        ]
    except Exception:
        return []


def _write_json_file(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _phase_parent_artifact(
    result: SubAgentResult,
    *,
    index: int,
    parent_run_dir: Path,
) -> dict[str, Any]:
    child_dir = Path(result.subagent_run_dir) if result.subagent_run_dir else None
    child_summary = _read_json_file(child_dir / "run_summary.json") if child_dir is not None else {}
    started_at = child_summary.get("started_at")
    ended_at = child_summary.get("ended_at")
    child_run_id = child_dir.name if child_dir is not None else None
    child_run_dir = str(child_dir) if child_dir is not None else None
    phase_dir = parent_run_dir / "phases" / f"{index:02d}_{result.role.value}"
    output = result.output or (f"SKIPPED: {result.skipped_reason}" if result.skipped_reason else "")
    return {
        "phase_name": result.role.value,
        "role": result.role.value,
        "attempt": result.attempt,
        "model": child_summary.get("model"),
        "status": result.status,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": result.duration_ms,
        "rounds": result.rounds,
        "output": output,
        "error": result.error,
        "skipped_reason": result.skipped_reason,
        "tool_calls": result.tool_calls,
        "allowed_tools": result.allowed_tools,
        "can_write": result.can_write,
        "input_prompt": result.task,
        "child_run_id": child_run_id,
        "child_run_dir": child_run_dir,
        "parent_phase_dir": str(phase_dir),
    }


def _structured_evidence(run: MultiAgentRun) -> dict[str, object]:
    return {
        "has_write_tool_evidence": has_write_tool_evidence(run.results),
        "write_task_lacks_evidence": write_task_lacks_evidence(run),
        "successful_tools": sorted(_run_successful_tools(run)),
        "expected_content_readback": _run_has_expected_content_readback(run),
        "security_verdict": _structured_security_verdict(run),
    }


def _persist_multiagent_parent_run(
    run_dir: Path,
    run: MultiAgentRun,
    selection: ModelSelection,
    config: AgentConfig,
    *,
    started_at: datetime,
    ended_at: datetime,
) -> None:
    """Persist a parent multi-agent workflow beside child subagent runs."""

    trace = _trace_payload(
        run,
        selection,
        config,
        started_at=started_at,
        ended_at=ended_at,
    )
    parent_run_id = run_dir.name
    final_status = str(trace["status"])
    final_answer = run.final_answer or ""
    phases = [
        _phase_parent_artifact(result, index=index, parent_run_dir=run_dir)
        for index, result in enumerate(run.results, start=1)
    ]
    run_json: dict[str, Any] = {
        "parent_run_id": parent_run_id,
        "prompt": run.user_prompt,
        "workspace": config.cwd,
        "model": selection.ollama_tag,
        "model_id": selection.model_id,
        "tool_mode": selection.tool_mode,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": trace["duration_seconds"],
        "initial_intent_decision": {
            "intent": run.intent,
            "requires_write": run.requires_write,
            "reason": run.intent_reason,
            "confidence": run.intent_confidence,
        },
        "orchestration_decision_final": {
            "selected_implementer": (
                run.selected_coder_role.value if run.selected_coder_role else None
            ),
            "final_status": final_status,
            "failed_phase": trace.get("failed_phase"),
            "error": run.error,
        },
        "phases_planned": trace["planned_phases"],
        "phases_executed": trace["executed_phases"],
        "repairs": [
            {
                "role": phase["role"],
                "attempt": phase["attempt"],
                "status": phase["status"],
            }
            for phase in phases
            if int(phase.get("attempt") or 1) > 1
        ],
        "structured_evidence": _structured_evidence(run),
        "final_status": final_status,
        "final_answer": final_answer,
        "child_runs": [
            {
                "phase_name": phase["phase_name"],
                "role": phase["role"],
                "child_run_id": phase["child_run_id"],
                "child_run_dir": phase["child_run_dir"],
            }
            for phase in phases
            if phase["child_run_id"]
        ],
        "phases": phases,
    }
    summary = {
        "parent_run_id": parent_run_id,
        "final_status": final_status,
        "phases_planned": trace["planned_phases"],
        "phases_executed": trace["executed_phases"],
        "selected_implementer": (
            run.selected_coder_role.value if run.selected_coder_role else None
        ),
        "child_run_count": len(run_json["child_runs"]),
        "final_answer_path": "final_answer.md",
        "run_json_path": "run.json",
    }

    _write_json_file(run_dir / "multiagent_trace.json", trace)
    _write_json_file(run_dir / "run.json", run_json)
    _write_json_file(run_dir / "summary.json", summary)
    (run_dir / "final_answer.md").write_text(final_answer, encoding="utf-8")
    trace_path = run_dir / "trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    for phase in phases:
        with trace_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(phase, ensure_ascii=False) + "\n")

    phases_dir = run_dir / "phases"
    phases_dir.mkdir(exist_ok=True)
    for phase in phases:
        phase_dir = Path(str(phase["parent_phase_dir"]))
        phase_dir.mkdir(parents=True, exist_ok=True)
        _write_json_file(phase_dir / "run.json", phase)
        (phase_dir / "output.md").write_text(
            str(phase.get("output") or ""),
            encoding="utf-8",
        )
        with (phase_dir / "tool_calls.jsonl").open("w", encoding="utf-8") as fh:
            for entry in phase.get("tool_calls") or []:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


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


def research_discovered_write_requirement(
    user_prompt: str,
    plan: SubAgentResult | None,
    research: SubAgentResult | None,
) -> bool:
    """Detect when document research reveals that a read-looking task needs code.

    Some prompts start as "read this PDF", but the document instructions can
    require implementing an exercise. Once the researcher finds strong
    implementation language, the orchestrator must promote the run to the
    write flow instead of finishing as a read-only answer.
    """

    text = _combined_output(plan, research).lower()
    if not text:
        return False
    if any(marker in text for marker in _RESEARCH_DISCOVERED_WRITE_MARKERS):
        return True
    has_code_context = any(
        marker in text
        for marker in ("python", ".py", "programming", "programación", "codigo", "código")
    )
    has_constraints = any(marker in text for marker in _CODE_CONSTRAINT_MARKERS)
    exercise_prompt = any(
        marker in (user_prompt or "").lower()
        for marker in ("exercise", "ejercicio", "examen", "follow the instructions")
    )
    return has_code_context and has_constraints and exercise_prompt


def promote_to_write_flow(
    run: MultiAgentRun,
    planned_phases: list[str],
) -> None:
    """Mutate orchestration state after research discovers implementation work."""

    run.requires_write = True
    run.intent = "code_change"
    for phase in ("coder", "validator", "reviewer", AgentRole.SECURITY_REVIEWER.value):
        if phase not in planned_phases:
            planned_phases.append(phase)
    run.planned_phases = planned_phases


def validation_failed(validation: SubAgentResult) -> bool:
    """Best-effort validation classifier for the first sequential version.

    Matching is word-boundary aware (via :func:`_contains_marker`) so a success
    token can no longer be matched as a substring of unrelated text — the bug
    where the literal content ``MULTIAGENTE_OK`` made ``ok`` look like a pass.

    A validator that reports *insufficient evidence* always counts as a failure
    and dominates any success token it may also echo, because a write task
    cannot be confirmed without real tool-call evidence.

    A validator with ``role_violation`` status also always counts as a failure
    because its checks may have been disrupted by the forbidden tool attempt.
    """
    if validation.status in {"role_violation", "invalid_tool_via_bash", "timeout", "failed"}:
        return True
    output = validation.output.lower()
    if _contains_marker(output, _INSUFFICIENT_EVIDENCE_MARKERS):
        return True
    has_success = _contains_marker(output, _VALIDATION_SUCCESS_MARKERS)
    has_failure = _contains_marker(output, _VALIDATION_FAILURE_MARKERS)
    if has_success and not has_failure:
        return False
    return has_failure


def should_repair_with_coder(validation: SubAgentResult) -> bool:
    """Return true only for actionable implementation failures.

    Some validation failures mean "the implementation is wrong" and should be
    sent back to the coder. Others mean "the validator/reviewer lacked evidence
    or violated its role"; re-running the coder in those cases causes noisy
    attempts even when the file is already correct.
    """
    if validation.status in {
        "role_violation",
        "invalid_tool_via_bash",
        "hallucinated_output",
        "tool_trace_failed",
        "timeout",
    }:
        return False
    text = "\n".join(part for part in (validation.output, validation.error or "") if part).lower()
    if any(marker in text for marker in _NON_ACTIONABLE_VALIDATION_FAILURE_MARKERS):
        return False
    return any(marker in text for marker in _ACTIONABLE_IMPLEMENTATION_FAILURE_MARKERS)


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
    if (
        run.contract_validation
        and run.contract_validation.kind == "exact_file_content"
        and run.contract_validation.status != "completed"
    ):
        return run.contract_validation.status
    last_validation = run.latest_for(AgentRole.VALIDATOR)
    if last_validation and validation_failed(last_validation):
        return "validation_failed"
    reviewer = run.latest_for(AgentRole.REVIEWER)
    if reviewer and validation_failed(reviewer):
        return "review_failed"
    security_reviewer = run.latest_for(AgentRole.SECURITY_REVIEWER)
    if security_reviewer and validation_failed(security_reviewer):
        return "security_failed"
    if run.requires_write and run.selected_coder_role is None:
        return "implementation_required_but_not_executed"
    if write_task_lacks_evidence(run):
        return "insufficient_evidence"
    return "completed"


def _contract_failure_class(contract: ContractValidation) -> str:
    failures = " ".join(contract.failures).lower()
    missing = set(contract.missing_evidence)
    if contract.scope_status == "failed" or contract.scope_failures:
        return "scope_violation"
    if "expected artifact is missing" in failures:
        return "missing_artifact"
    if "content does not match" in failures:
        return "content_mismatch"
    if "write_file" in missing:
        return "missing_write_evidence"
    if "read_file" in missing:
        return "missing_readback_evidence"
    if contract.status == "insufficient_evidence":
        return "insufficient_evidence"
    if contract.status == "validation_failed":
        return "validator_failed"
    return "unknown_failure"


def _phase_for_failure(run: MultiAgentRun, status: str) -> SubAgentResult | None:
    role_by_status = {
        "validation_failed": AgentRole.VALIDATOR,
        "review_failed": AgentRole.REVIEWER,
        "security_failed": AgentRole.SECURITY_REVIEWER,
    }
    role = role_by_status.get(status)
    if role is not None:
        return run.latest_for(role)
    for result in reversed(run.results):
        if result.status in {
            "role_violation",
            "invalid_tool_via_bash",
            "timeout",
            "failed",
            "blocked",
        }:
            return result
    return None


def classify_failure_classification(run: MultiAgentRun) -> FailureClassification | None:
    """Return a small structured reason for non-completed multi-agent status."""
    if run.error:
        return FailureClassification(
            status="failed",
            failure_class="unknown_failure",
            failure_reason=_shorten(run.error, limit=400),
            failed_phase=run.failed_phase,
            repairable=False,
            related_evidence=sorted(_run_successful_tools(run)),
            details={"run_error": run.error},
        )
    status = final_run_status(run)
    if status == "completed":
        return None

    contract = run.contract_validation
    if contract and contract.kind == "exact_file_content" and contract.status != "completed":
        failure_class = _contract_failure_class(contract)
        reason_parts = contract.failures or contract.notes or [contract.status]
        return FailureClassification(
            status=status,
            failure_class=failure_class,
            failure_reason="; ".join(reason_parts),
            failed_phase=run.selected_coder_role.value if run.selected_coder_role else None,
            repairable=failure_class in {"content_mismatch", "missing_artifact"},
            related_evidence=contract.observed_evidence + contract.missing_evidence,
            contract_kind=contract.kind,
            details={
                "contract_status": contract.status,
                "missing_evidence": contract.missing_evidence,
                "failures": contract.failures,
            },
        )

    failed_result = _phase_for_failure(run, status)
    failed_phase = failed_result.role.value if failed_result else run.failed_phase
    if failed_result and failed_result.status == "role_violation":
        failure_class = "role_violation"
    elif status == "validation_failed":
        failure_class = "validator_failed"
    elif status == "review_failed":
        failure_class = "review_failed"
    elif status == "security_failed":
        failure_class = "security_failed"
    elif status == "insufficient_evidence":
        failure_class = "insufficient_evidence"
    else:
        failure_class = "unknown_failure"
    reason = ""
    if failed_result:
        reason = failed_result.error or failed_result.output
    if not reason:
        reason = status
    return FailureClassification(
        status=status,
        failure_class=failure_class,
        failure_reason=_shorten(reason, limit=400),
        failed_phase=failed_phase,
        repairable=status == "validation_failed"
        and bool(failed_result and should_repair_with_coder(failed_result)),
        related_evidence=sorted(_run_successful_tools(run)),
        contract_kind=contract.kind if contract else None,
        details={"run_status": status},
    )


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
        "Evidence discipline: do NOT claim to have created, verified, or modified "
        "any file, and do NOT claim the diff is empty — report only facts confirmed "
        "by your read-tool results. If you have no tool result for something, say "
        "it was not inspected.\n\n"
        "Report:\n"
        "- requirements and needed checks you identified\n"
        "- context confirmed by your actual read-tool calls\n"
        "- the verbatim content the implementer will need (quoted in full)\n"
        "- relevant files, APIs, constraints, and risks\n"
        "- any missing dependency as `BLOCKED:` if the plan cannot continue\n\n"
        f"User task:\n{user_prompt}\n\nPlan:\n{plan_text}"
    )


def _file_content_contract_instruction(user_prompt: str) -> str:
    """Return extra implementer guidance for explicit file/content contracts."""
    if not _FILE_CONTENT_CONTRACT_FILE_RE.search(user_prompt or ""):
        return ""
    if not _FILE_CONTENT_CONTRACT_CONTENT_RE.search(user_prompt or ""):
        return ""
    return (
        "File creation contract detected:\n"
        "- First write the requested file using `write_file`.\n"
        "- Then verify it by reading the same path with `read_file`.\n"
        "- Do not claim completion unless the readback content matches the "
        "requested exact content.\n"
        "- In your final answer, explicitly include:\n"
        "  Tool used: write_file\n"
        "  Verification tool used: read_file"
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
    contract_instruction = _file_content_contract_instruction(user_prompt)
    contract_block = f"{contract_instruction}\n\n" if contract_instruction else ""
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
        "Your deliverable is the actual file(s) the task requires, WRITTEN TO "
        "DISK with their real content — not a description and not empty code "
        "blocks. Create every file the task calls for (the program/solution it "
        "asks you to build, and any tests it explicitly requests), and do not "
        "claim the task is complete until those files exist with real content.\n\n"
        f"{contract_block}User task:\n{user_prompt}\n\nPlan:\n{plan_text}\n\n"
        f"Research:\n{research_text}"
    )


def _requires_change_scope_evidence(*texts: str | None) -> bool:
    combined = "\n".join(text or "" for text in texts).lower()
    return any(marker in combined for marker in _CHANGE_SCOPE_REQUEST_MARKERS)


def _change_scope_instruction(required: bool) -> str:
    if not required:
        return ""
    return (
        "Mandatory change-scope inspection:\n"
        "- Call `git_status` for the workspace.\n"
        "- Call `git_diff` for the workspace.\n"
        "- Base every claim about the final diff or unchanged files on those real "
        "tool results.\n"
        "- Do not report PASS for diff/scope if either call is missing or failed; "
        "report `insufficient evidence` and name the missing tool instead."
    )


def _enforce_change_scope_evidence(
    result: SubAgentResult,
    *,
    required: bool,
) -> SubAgentResult:
    """Reject narrative PASS claims when mandatory diff evidence is absent."""
    if not required:
        return result
    successful = {
        _tool_name(entry)
        for entry in result.tool_calls
        if _tool_ok(entry) and _tool_name(entry) in _CHANGE_SCOPE_EVIDENCE_TOOLS
    }
    missing = sorted(_CHANGE_SCOPE_EVIDENCE_TOOLS - successful)
    if not missing:
        return result
    detail = "missing successful tool evidence: " + ", ".join(missing)
    result.status = "failed"
    result.error = detail
    scope_failure = (
        "Insufficient evidence: final diff/scope review was required, but "
        f"{detail}. Do not report PASS for change scope."
    )
    prior_output = result.output.strip()
    prior_is_failure = any(
        marker in prior_output.lower()
        for marker in ("insufficient evidence", "failed", "failure", "error")
    )
    result.output = (
        f"{prior_output}\n\n{scope_failure}" if prior_output and prior_is_failure else scope_failure
    )
    return result


def _required_tools_satisfied(
    result: SubAgentResult,
    required_tools: set[str] | frozenset[str],
) -> bool:
    if not required_tools:
        return False
    successful = {_tool_name(entry) for entry in result.tool_calls if _tool_ok(entry)}
    return set(required_tools) <= successful


def _successful_tool_entries(
    results: list[SubAgentResult],
    required_tools: list[str] | tuple[str, ...] | set[str] | frozenset[str],
) -> list[dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    required_set = set(required_tools)
    for result in results:
        for entry in result.tool_calls:
            name = _tool_name(entry)
            if name in required_set and _tool_ok(entry) and name not in found:
                found[name] = dict(entry)
    return [found[name] for name in required_tools if name in found]


def _finalize_if_evidence_satisfied(
    result: SubAgentResult,
    *,
    required_tools: set[str] | frozenset[str],
    verdict: str,
) -> SubAgentResult:
    """Prefer real satisfied evidence over later/narrative validator drift."""
    if not _required_tools_satisfied(result, required_tools):
        return result
    result.status = "completed"
    result.error = None
    result.output = verdict
    return result


def _deterministic_scope_review_result(
    role: AgentRole,
    task_prompt: str,
    config: AgentConfig,
    *,
    verdict: str,
    prior_results: list[SubAgentResult] | None = None,
) -> SubAgentResult:
    """Collect required scope evidence without relying on reviewer LLM behavior."""

    tool_entries: list[dict[str, object]] = []
    required_tools = ("git_status", "git_diff")
    prior_results = prior_results or []
    prior_validation = next(
        (result for result in reversed(prior_results) if result.role == AgentRole.VALIDATOR),
        None,
    )
    if prior_validation and validation_failed(prior_validation):
        output = (
            "Insufficient evidence: prior validation failed, so scope review "
            "cannot report PASS. Do not report PASS for change scope."
        )
        spec = ROLE_SPECS[role]
        return SubAgentResult(
            role=role,
            task=task_prompt,
            output=output,
            status="failed",
            error=output,
            role_anchor=None,
            allowed_tools=sorted(config.skill_allowed_tools or ()),
            can_write=spec.can_write,
            input_prompt=_shorten(task_prompt, limit=600),
            tool_calls=[],
            rounds=0,
        )

    prior_entries = _successful_tool_entries(prior_results, required_tools)
    if {entry["tool"] for entry in prior_entries} >= set(required_tools):
        tool_entries = prior_entries
    else:
        # These deterministic scope checks are read-only and are part of the
        # validator/reviewer contract itself. Avoid routing them through an
        # interactive approval prompt, which would make non-interactive
        # multi-agent runs hang after the evidence is already known to be
        # required.
        read_only_config = replace(config, auto_confirm=True)
        for name in ("git_status", "git_diff"):
            call = ToolCall(name=name, arguments={"path": "."})
            result = execute_tool(call, read_only_config)
            tool_entries.append(
                {
                    "tool": name,
                    "ok": not result.is_error,
                    "outcome": result.outcome,
                    "arguments": call.arguments,
                    "output_preview": result.content[:600],
                    "error_preview": result.content[:600] if result.is_error else None,
                }
            )

    if all(_tool_ok(entry) for entry in tool_entries):
        status = "completed"
        output = verdict
        error = None
    else:
        missing = ", ".join(_tool_name(entry) for entry in tool_entries if not _tool_ok(entry))
        status = "failed"
        output = f"FAIL: missing successful scope evidence: {missing}."
        error = output

    spec = ROLE_SPECS[role]
    return SubAgentResult(
        role=role,
        task=task_prompt,
        output=output,
        status=status,
        error=error,
        role_anchor=None,
        allowed_tools=sorted(config.skill_allowed_tools or ()),
        can_write=spec.can_write,
        input_prompt=_shorten(task_prompt, limit=600),
        tool_calls=tool_entries,
        rounds=0,
    )


def _can_use_deterministic_validation(
    contract: ValidationContract,
    config: AgentConfig,
    implementation: SubAgentResult,
) -> bool:
    tools = set(contract.required_evidence_tools)
    if not tools or "bash" in tools:
        return False
    if not tools <= {"read_file", "git_status", "git_diff"}:
        return False
    if {"git_status", "git_diff"} & tools and not _git_scope_tools_available(config.cwd):
        return False
    if "read_file" not in tools:
        return True
    expected_path = contract.expected_artifacts[0] if contract.expected_artifacts else None
    if expected_path and not (Path(config.cwd) / expected_path).exists():
        return False
    if expected_path:
        return True
    expected_content = next(
        (
            value
            for value in contract.expected_contents_or_properties
            if "outside the requested scope" not in value.lower()
        ),
        None,
    )
    for entry in implementation.tool_calls:
        if _entry_satisfies_readback(
            entry,
            expected_path=expected_path,
            expected_content=expected_content,
        ):
            return True
    return False


def _entry_satisfies_readback(
    entry: dict[str, object],
    *,
    expected_path: str | None,
    expected_content: str | None,
) -> bool:
    if _tool_name(entry) != "read_file" or not _tool_ok(entry):
        return False
    if expected_path and expected_path.replace("\\", "/") not in _tool_target(entry).replace(
        "\\", "/"
    ):
        return False
    return expected_content is None or expected_content in _tool_output_preview(entry, limit=2000)


def _implementation_readback_entry(
    contract: ValidationContract,
    implementation: SubAgentResult,
) -> dict[str, object] | None:
    expected_path = contract.expected_artifacts[0] if contract.expected_artifacts else None
    expected_content = next(
        (
            value
            for value in contract.expected_contents_or_properties
            if "outside the requested scope" not in value.lower()
        ),
        None,
    )
    return next(
        (
            entry
            for entry in implementation.tool_calls
            if _entry_satisfies_readback(
                entry,
                expected_path=expected_path,
                expected_content=expected_content,
            )
        ),
        None,
    )


def _deterministic_validation_result(
    contract: ValidationContract,
    task_prompt: str,
    config: AgentConfig,
    implementation: SubAgentResult,
) -> SubAgentResult:
    """Run compact validation contracts directly when no shell/test command is needed."""

    tool_entries: list[dict[str, object]] = []
    read_only_config = replace(config, auto_confirm=True)
    expected_path = contract.expected_artifacts[0] if contract.expected_artifacts else None
    expected_content = next(
        (
            value
            for value in contract.expected_contents_or_properties
            if "outside the requested scope" not in value.lower()
        ),
        None,
    )
    for name in contract.required_evidence_tools:
        if name == "read_file" and expected_path:
            prior_readback = _implementation_readback_entry(contract, implementation)
            if prior_readback and not (Path(config.cwd) / expected_path).exists():
                tool_entries.append(dict(prior_readback))
                continue
            arguments = {"path": expected_path}
        elif name in {"git_status", "git_diff"}:
            arguments = {"path": "."}
        else:
            continue
        call = ToolCall(name=name, arguments=arguments)
        result = execute_tool(call, read_only_config)
        ok = not result.is_error
        if name == "read_file" and expected_content and expected_content not in result.content:
            ok = False
        tool_entries.append(
            {
                "tool": name,
                "ok": ok,
                "outcome": result.outcome,
                "arguments": call.arguments,
                "output_preview": result.content[:600],
                "error_preview": result.content[:600] if not ok else None,
            }
        )

    successful = {_tool_name(entry) for entry in tool_entries if _tool_ok(entry)}
    required = set(contract.required_evidence_tools) - {"bash"}
    if required <= successful:
        status = "completed"
        output = "PASS: required validation evidence tools completed successfully."
        error = None
    else:
        missing = ", ".join(sorted(required - successful))
        status = "failed"
        output = f"FAIL: missing successful validation evidence: {missing}."
        error = output

    return SubAgentResult(
        role=AgentRole.VALIDATOR,
        task=task_prompt,
        output=output,
        status=status,
        error=error,
        role_anchor=None,
        allowed_tools=sorted(config.skill_allowed_tools or ()),
        can_write=ROLE_SPECS[AgentRole.VALIDATOR].can_write,
        input_prompt=_shorten(task_prompt, limit=600),
        tool_calls=tool_entries,
        rounds=0,
    )


def _extract_prompt_paths(*texts: str | None) -> list[str]:
    values: list[str] = []
    for text in texts:
        values.extend(_PROMPT_PATH_RE.findall(text or ""))
    return _unique_preserving_order(values)


def _extract_expected_content(user_prompt: str) -> str | None:
    match = _PROMPT_EXACT_CONTENT_RE.search(user_prompt or "")
    if not match:
        return None
    value = next((group for group in match.groups() if group), None)
    return value.rstrip(".,;") if value else None


def _extract_test_commands(*texts: str | None) -> list[str]:
    commands: list[str] = []
    for text in texts:
        commands.extend(match.group(0).strip() for match in _PYTEST_COMMAND_RE.finditer(text or ""))
    return _unique_preserving_order(commands)


def _baseline_summary(git_baseline: str | None, expected_paths: list[str]) -> str:
    if not git_baseline or git_baseline == "(clean)":
        return "Baseline summary: clean or unavailable."
    lines = [line.strip() for line in git_baseline.splitlines() if line.strip()]
    relevant = [
        line
        for line in lines
        if any(path.replace("\\", "/") in line.replace("\\", "/") for path in expected_paths)
    ]
    if relevant:
        return "Pre-run WIP relevant to expected paths: " + "; ".join(relevant[:8])
    preview = "; ".join(lines[:8])
    suffix = f"; ... {len(lines) - 8} more paths" if len(lines) > 8 else ""
    return f"Pre-run WIP exists ({len(lines)} status entr{'y' if len(lines) == 1 else 'ies'}): {preview}{suffix}"


def _implementation_evidence_summary(implementation: SubAgentResult) -> str:
    if not implementation.tool_calls:
        return "No implementation tool evidence recorded."
    lines: list[str] = []
    for entry in implementation.tool_calls[:12]:
        name = _tool_name(entry)
        ok = "OK" if _tool_ok(entry) else "ERROR"
        target = _tool_target(entry)
        preview = _tool_output_preview(entry, limit=80)
        suffix = f" -> {preview}" if preview else ""
        lines.append(f"- {name}({target}) {ok}{suffix}")
    if len(implementation.tool_calls) > 12:
        lines.append(f"- ... {len(implementation.tool_calls) - 12} more tool call(s)")
    return "\n".join(lines)


def _run_successful_tools(run: MultiAgentRun) -> set[str]:
    return {
        _tool_name(entry)
        for result in run.results
        for entry in result.tool_calls
        if _tool_ok(entry)
    }


def _run_has_expected_content_readback(run: MultiAgentRun) -> bool:
    expected = _extract_expected_content(run.user_prompt)
    if not expected:
        return True
    for result in run.results:
        for entry in result.tool_calls:
            if not _tool_ok(entry) or _tool_name(entry) not in _READBACK_EVIDENCE_TOOLS:
                continue
            preview = _tool_output_preview(entry, limit=2000)
            if expected in preview:
                return True
    return False


def _exact_file_content_contract(user_prompt: str) -> tuple[str, str] | None:
    """Return the narrow exact file/content contract from a user prompt."""
    file_match = _FILE_CONTENT_CONTRACT_FILE_RE.search(user_prompt or "")
    content_match = _FILE_CONTENT_CONTRACT_CONTENT_RE.search(user_prompt or "")
    if not file_match or not content_match:
        return None
    content = next((group for group in content_match.groups() if group), None)
    if not content:
        return None
    return file_match.group(1).rstrip(".,;"), content.rstrip(".,;")


def _path_matches_tool_target(entry: dict[str, object], expected_path: str) -> bool:
    target = _tool_target(entry)
    if target == "(target unknown)":
        return False
    return target.replace("\\", "/") == expected_path.replace("\\", "/")


def _has_exact_write_evidence(entries: list[dict[str, object]], path: str) -> bool:
    return any(
        _tool_ok(entry)
        and _tool_name(entry) in _WRITE_EVIDENCE_TOOLS
        and _path_matches_tool_target(entry, path)
        for entry in entries
    )


def _has_exact_readback_evidence(
    entries: list[dict[str, object]],
    *,
    path: str,
    content: str,
) -> bool:
    return any(
        _tool_ok(entry)
        and _tool_name(entry) in _READBACK_EVIDENCE_TOOLS
        and _path_matches_tool_target(entry, path)
        and content in _tool_output_preview(entry, limit=2000)
        for entry in entries
    )


def _normalize_scope_path(path: str) -> str:
    return path.strip().strip("`\"'.,;").replace("\\", "/").lstrip("./")


def _infer_write_scope(
    user_prompt: str,
    *,
    expected_path: str | None = None,
) -> tuple[list[str], list[str]]:
    """Infer narrow explicit write scope from the user prompt."""
    text = user_prompt or ""
    paths: list[str] = []
    roots: list[str] = []
    if expected_path and _NO_OTHER_FILE_RE.search(text):
        paths.append(_normalize_scope_path(expected_path))
    for match in _ONLY_MODIFY_PATH_RE.finditer(text):
        paths.append(_normalize_scope_path(match.group(1)))
    for match in _WORK_ONLY_FOLDER_RE.finditer(text):
        roots.append(_normalize_scope_path(match.group(1)).rstrip("/") + "/")
    return _unique_preserving_order(paths), _unique_preserving_order(roots)


def _parse_git_status_paths(output: str) -> list[str]:
    paths: list[str] = []
    for raw_line in (output or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if not (len(line) > 3 and line[2] == " " and line[:2].strip()):
            continue
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        path = _normalize_scope_path(path)
        if path:
            paths.append(path)
    return paths


def _parse_git_diff_paths(output: str) -> list[str]:
    paths: list[str] = []
    for raw_line in (output or "").splitlines():
        match = _DIFF_PATH_RE.match(raw_line.strip())
        if not match:
            continue
        for value in match.groups():
            path = _normalize_scope_path(value)
            if path and path != "/dev/null":
                paths.append(path)
    return paths


def _observed_changed_paths_from_evidence(entries: list[dict[str, object]]) -> list[str]:
    paths: list[str] = []
    for entry in entries:
        if not _tool_ok(entry):
            continue
        output = str(entry.get("output_preview") or entry.get("output") or "")
        if _tool_name(entry) == "git_status":
            paths.extend(_parse_git_status_paths(output))
        elif _tool_name(entry) == "git_diff":
            paths.extend(_parse_git_diff_paths(output))
    return _unique_preserving_order(paths)


def _path_allowed_by_scope(
    path: str,
    *,
    allowed_paths: list[str],
    allowed_roots: list[str],
) -> bool:
    normalized = _normalize_scope_path(path)
    if normalized in allowed_paths:
        return True
    return any(normalized.startswith(root) for root in allowed_roots)


def _scope_status(
    *,
    allowed_paths: list[str],
    allowed_roots: list[str],
    observed_paths: list[str],
    has_scope_evidence: bool,
) -> tuple[str | None, list[str]]:
    if not allowed_paths and not allowed_roots:
        return None, []
    if not has_scope_evidence:
        return "not_evaluated", []
    if not observed_paths:
        return "passed", []
    violations = [
        path
        for path in observed_paths
        if not _path_allowed_by_scope(
            path,
            allowed_paths=allowed_paths,
            allowed_roots=allowed_roots,
        )
    ]
    if violations:
        return "failed", [f"changed path outside allowed scope: {path}" for path in violations]
    return "passed", []


def classify_exact_file_content_contract(
    run: MultiAgentRun,
    config: AgentConfig,
) -> ContractValidation | None:
    """Classify the narrow "create file with exact content" contract, if present."""
    contract = _exact_file_content_contract(run.user_prompt)
    if contract is None:
        return None

    expected_path, expected_content = contract
    full_path = Path(config.cwd) / expected_path
    exists = full_path.exists()
    observed_content: str | None = None
    read_error: str | None = None
    if exists:
        try:
            observed_content = full_path.read_text(encoding="utf-8")
        except Exception as exc:
            read_error = str(exc)
    content_matches = observed_content == expected_content

    entries = _evidence_entries(run.results)
    write_evidence = _has_exact_write_evidence(entries, expected_path)
    readback_evidence = _has_exact_readback_evidence(
        entries,
        path=expected_path,
        content=expected_content,
    )
    allowed_write_paths, allowed_write_roots = _infer_write_scope(
        run.user_prompt,
        expected_path=expected_path,
    )
    observed_changed_paths = _observed_changed_paths_from_evidence(entries)
    has_scope_evidence = any(
        _tool_ok(entry) and _tool_name(entry) in _CHANGE_SCOPE_EVIDENCE_TOOLS for entry in entries
    )
    scope_status, scope_failures = _scope_status(
        allowed_paths=allowed_write_paths,
        allowed_roots=allowed_write_roots,
        observed_paths=observed_changed_paths,
        has_scope_evidence=has_scope_evidence,
    )
    observed_evidence = []
    if write_evidence:
        observed_evidence.append("write_file")
    if readback_evidence:
        observed_evidence.append("read_file")
    if has_scope_evidence:
        observed_evidence.append("scope")
    required_evidence = ["write_file", "read_file"]
    if scope_status is not None:
        required_evidence.append("scope")
    missing_evidence = [
        name
        for name, present in (
            ("write_file", write_evidence),
            ("read_file", readback_evidence),
            ("scope", scope_status is None or scope_status in {"passed", "failed"}),
        )
        if not present
    ]

    failures: list[str] = []
    notes: list[str] = []
    last_validation = run.latest_for(AgentRole.VALIDATOR)
    validator_failed = bool(last_validation and validation_failed(last_validation))
    validator_text = (
        "\n".join((last_validation.output, last_validation.error or "")).lower()
        if last_validation
        else ""
    )
    validator_functional_failure = validator_failed and any(
        marker in validator_text for marker in _ACTIONABLE_IMPLEMENTATION_FAILURE_MARKERS
    )

    if read_error:
        failures.append(f"could not read expected artifact: {read_error}")
    if exists and not content_matches:
        failures.append("expected artifact content does not match")
    if validator_functional_failure:
        failures.append("validator reported functional contract failure")
    if not exists:
        failures.append("expected artifact is missing")
    failures.extend(scope_failures)
    for item in missing_evidence:
        notes.append(f"missing required evidence: {item}")

    if scope_status == "not_evaluated":
        notes.append("missing required scope evidence: git_status or git_diff")

    if scope_status == "failed":
        status = "validation_failed"
    elif scope_status == "not_evaluated":
        status = "insufficient_evidence"
    elif exists and content_matches and not missing_evidence and not validator_functional_failure:
        status = "completed"
    elif exists and (not content_matches or validator_functional_failure):
        status = "validation_failed"
    elif exists and content_matches and missing_evidence:
        status = "tool_trace_failed"
    else:
        status = "insufficient_evidence"

    observed_artifact: dict[str, object] = {
        "path": expected_path,
        "exists": exists,
        "content_matches": content_matches if observed_content is not None else False,
    }
    if observed_content is not None:
        observed_artifact["content_hash"] = hashlib.sha256(
            observed_content.encode("utf-8")
        ).hexdigest()
    if read_error:
        observed_artifact["read_error"] = read_error

    return ContractValidation(
        kind="exact_file_content",
        status=status,
        expected_artifacts=[
            {
                "path": expected_path,
                "content_hash": hashlib.sha256(expected_content.encode("utf-8")).hexdigest(),
                "content_preview": _shorten(expected_content, limit=120),
            }
        ],
        observed_artifacts=[observed_artifact],
        required_evidence=required_evidence,
        observed_evidence=observed_evidence,
        missing_evidence=missing_evidence,
        failures=failures,
        notes=notes,
        allowed_write_paths=allowed_write_paths,
        allowed_write_roots=allowed_write_roots,
        observed_changed_paths=observed_changed_paths,
        scope_status=scope_status,
        scope_failures=scope_failures,
    )


def _refresh_contract_validation(run: MultiAgentRun, config: AgentConfig) -> None:
    run.contract_validation = classify_exact_file_content_contract(run, config)
    run.failure_classification = classify_failure_classification(run)


def _ignored_invalid_tool_warnings(run: MultiAgentRun) -> list[str]:
    warnings: list[str] = []
    for result in run.results:
        if result.status != "completed":
            continue
        for entry in result.tool_calls:
            if entry.get("outcome") == "invalid_tool_via_bash":
                warnings.append(f"{result.role.value} attempted an ignored pseudo-tool via bash")
    return warnings


def _structured_security_verdict(run: MultiAgentRun) -> str:
    tools = _run_successful_tools(run)
    missing: list[str] = []
    if has_write_tool_evidence(run.results) and not _run_has_expected_content_readback(run):
        missing.append("content readback evidence")
    if _requires_change_scope_evidence(run.user_prompt, *(r.output for r in run.results)):
        for tool in ("git_status", "git_diff"):
            if tool not in tools:
                missing.append(tool)
    if missing:
        return "FAIL: unresolved security/permission evidence gaps: " + ", ".join(missing)
    warnings = _ignored_invalid_tool_warnings(run)
    if warnings:
        return "WARN: Evidence requirements were satisfied; " + "; ".join(warnings) + "."
    return "PASS: No unresolved permission/security issues. Security review passed."


def build_validation_contract(
    user_prompt: str,
    plan: SubAgentResult | None,
    research: SubAgentResult | None,
    implementation: SubAgentResult,
    *,
    git_baseline: str | None = None,
) -> ValidationContract:
    """Derive a compact, general validation contract for the validator phase."""
    prompt_lower = (user_prompt or "").lower()
    intent_text = re.sub(
        r"\b(?:do not|don't|no)\s+(?:modify|change|edit|write|create)\b",
        "",
        prompt_lower,
    )
    plan_text = plan.output if plan else ""
    research_text = research.output if research else ""
    expected_paths = _extract_prompt_paths(user_prompt, plan_text, implementation.output)
    expected_content = _extract_expected_content(user_prompt)
    test_commands = _extract_test_commands(user_prompt, plan_text, research_text)
    scope_required = _requires_change_scope_evidence(user_prompt, plan_text)
    task_type = (
        "read_only"
        if not _contains_marker(intent_text, _IMPLEMENTATION_TASK_MARKERS)
        else "code_change"
        if any(path.endswith(".py") for path in expected_paths) or test_commands
        else "file_change"
    )
    required_tools: list[str] = []
    checks: list[str] = []
    if expected_paths:
        required_tools.append("read_file")
        checks.append("Read each expected artifact and verify it exists.")
    if expected_content:
        checks.append(f"Verify expected content/property: {expected_content}")
    if test_commands:
        required_tools.append("bash")
        checks.extend(f"Run focused test command: {cmd}" for cmd in test_commands)
    if scope_required:
        required_tools.extend(["git_status", "git_diff"])
        checks.append("Inspect change scope with git_status and git_diff.")
    if not checks:
        checks.append(
            "Validate the implementation against the user request using the smallest sufficient read/check tools."
        )
    expected_properties = []
    if expected_content:
        expected_properties.append(expected_content)
    if (
        "no modifiques" in prompt_lower
        or "do not modify" in prompt_lower
        or "no other files" in prompt_lower
    ):
        expected_properties.append("No files outside the requested scope should be changed.")
    return ValidationContract(
        task_type=task_type,
        expected_artifacts=expected_paths,
        expected_contents_or_properties=expected_properties,
        required_checks=checks,
        required_evidence_tools=_unique_preserving_order(required_tools),
        expected_changed_paths=expected_paths,
        forbidden_changed_paths=["paths outside expected_changed_paths"] if scope_required else [],
        scope_check_required=scope_required,
        test_commands=test_commands,
        baseline_summary=_baseline_summary(git_baseline, expected_paths),
        implementation_evidence_summary=_implementation_evidence_summary(implementation),
    )


def _format_contract_list(values: list[str]) -> str:
    if not values:
        return "- none"
    return "\n".join(f"- {value}" for value in values)


def _format_validation_contract(contract: ValidationContract) -> str:
    return (
        "ValidationContract\n"
        f"task_type: {contract.task_type}\n"
        "expected_artifacts:\n"
        f"{_format_contract_list(contract.expected_artifacts)}\n"
        "expected_contents_or_properties:\n"
        f"{_format_contract_list(contract.expected_contents_or_properties)}\n"
        "required_checks:\n"
        f"{_format_contract_list(contract.required_checks)}\n"
        "required_evidence_tools:\n"
        f"{_format_contract_list(contract.required_evidence_tools)}\n"
        "expected_changed_paths:\n"
        f"{_format_contract_list(contract.expected_changed_paths)}\n"
        "forbidden_changed_paths:\n"
        f"{_format_contract_list(contract.forbidden_changed_paths)}\n"
        f"scope_check_required: {contract.scope_check_required}\n"
        "test_commands:\n"
        f"{_format_contract_list(contract.test_commands)}\n"
        f"baseline_summary: {contract.baseline_summary}\n"
        "implementation_evidence_summary:\n"
        f"{contract.implementation_evidence_summary}"
    )


def _validator_config_for_contract(
    config: AgentConfig,
    contract: ValidationContract,
) -> AgentConfig:
    """Restrict validator tools to the contract; include bash only for real tests."""
    tools = set(contract.required_evidence_tools)
    if contract.test_commands:
        tools.add("bash")
    else:
        tools.discard("bash")
    if not tools:
        tools.add("read_file")
    if config.skill_allowed_tools is not None:
        tools &= set(config.skill_allowed_tools)
    return replace(
        config,
        skill_allowed_tools=frozenset(tools),
        required_evidence_tools=frozenset(tools - {"bash"}),
        evidence_completion_verdict=(
            "PASS: required validation evidence tools completed successfully."
        ),
    )


def _reviewer_config_for_scope(
    config: AgentConfig,
    *,
    scope_required: bool,
) -> AgentConfig:
    if not scope_required:
        return config
    tools = {"git_status", "git_diff"}
    if config.skill_allowed_tools is not None:
        tools &= set(config.skill_allowed_tools)
    return replace(
        config,
        skill_allowed_tools=frozenset(tools),
        required_evidence_tools=frozenset(tools),
        evidence_completion_verdict=(
            "PASS: required review scope evidence tools completed successfully."
        ),
    )


def _build_validation_prompt(
    user_prompt: str,
    plan: SubAgentResult,
    research: SubAgentResult,
    implementation: SubAgentResult,
    *,
    git_baseline: str | None = None,
) -> str:
    """Build the validator subagent's task prompt from the plan, research, and implementation."""
    contract = build_validation_contract(
        user_prompt,
        plan,
        research,
        implementation,
        git_baseline=git_baseline,
    )
    evidence = _build_tool_evidence_report(
        user_prompt,
        [implementation],
        selected_coder_role=implementation.role,
    )
    return (
        "Validate the implementation using ONLY this compact contract. Do not "
        "ask for more context and do not keep iterating after required evidence "
        "is collected. Follow the planner's validation expectations only as "
        "summarized in the contract. If the implementation did not follow the "
        "plan, report FAIL with the mismatch.\n\n"
        "Forbidden tools: do NOT call `todo_write`, `write_file`, `edit_file`, "
        "`apply_patch`, or `notebook_edit`. Do not use todo planning tools. "
        "Use dedicated tools directly: call `read_file`, `git_status`, and "
        "`git_diff` as tools, never by typing their names into `bash`. Use "
        "`bash` only for real shell test commands such as pytest.\n\n"
        "Emit `PASS:` or `FAIL:` only as plain final text. Never put `PASS:` "
        "or `FAIL:` inside a fenced code/tool block, and never call them as "
        "bash commands.\n\n"
        "Execute exactly the required_checks. When all required_evidence_tools "
        "have succeeded, stop tool use and return a final verdict starting with "
        "`PASS:` or `FAIL:`. If required evidence is missing, return `FAIL: "
        "insufficient evidence` and name the missing tool/check.\n\n"
        f"{_change_scope_instruction(contract.scope_check_required)}\n\n"
        f"{_format_validation_contract(contract)}\n\n"
        f"{_evidence_rules()}\n\n"
        f"{evidence}\n\n"
        f"User task summary:\n{_shorten(user_prompt, limit=360)}"
    )


def _build_repair_prompt(
    user_prompt: str,
    plan: SubAgentResult,
    research: SubAgentResult,
    previous_implementation: SubAgentResult,
    validation: SubAgentResult,
) -> str:
    """Build the repair prompt that asks the implementer to fix a validation failure."""
    contract_instruction = _file_content_contract_instruction(user_prompt)
    contract_block = f"{contract_instruction}\n\n" if contract_instruction else ""
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
        f"{contract_block}User task:\n{user_prompt}\n\nPlan:\n{plan.output}\n\n"
        f"Research:\n{research.output}\n\nPrevious implementation:\n"
        f"{previous_implementation.output}\n\nValidation failure:\n"
        f"{validation.output}"
    )


def _build_review_prompt(run: MultiAgentRun) -> str:
    """Build the reviewer subagent's prompt from the full run's accumulated evidence."""
    tool_evidence = _build_tool_evidence_report(
        run.user_prompt,
        run.results,
        selected_coder_role=run.selected_coder_role,
    )
    scope_required = _requires_change_scope_evidence(
        run.user_prompt,
        *(result.output for result in run.results),
    )
    baseline = _baseline_summary(run.git_baseline, _extract_prompt_paths(run.user_prompt))
    phase_summary = "\n".join(
        f"- {result.role.value} attempt {result.attempt}: status={result.status}; "
        f"output={_shorten(result.output, limit=180)}"
        for result in run.results
    )
    return (
        "Review the completed multi-agent run using this compact review "
        "contract against the planner's execution plan summary. Do not modify "
        "files. Check that phases avoided overlapping responsibilities. Do not "
        "ask for more context.\n\n"
        "Forbidden tools: do NOT call `todo_write`, `write_file`, `edit_file`, "
        "`apply_patch`, or `notebook_edit`. Your review must be grounded only "
        "in the task, run evidence, and your `git_status`/`git_diff` results. "
        "Do not mention files, tools, or artifacts not present in the task or "
        "real tool-call evidence.\n\n"
        f"{_change_scope_instruction(scope_required)}\n\n"
        f"baseline_summary: {baseline}\n"
        f"scope_check_required: {scope_required}\n"
        "phase_summary:\n"
        f"{phase_summary}\n\n"
        f"{_evidence_rules()}\n\n"
        f"{tool_evidence}\n\n"
        f"User task summary:\n{_shorten(run.user_prompt, limit=360)}"
    )


def _build_security_review_prompt(run: MultiAgentRun) -> str:
    """Build the security reviewer subagent's prompt from the run's accumulated evidence."""
    tool_evidence = _build_tool_evidence_report(
        run.user_prompt,
        run.results,
        selected_coder_role=run.selected_coder_role,
    )
    scope_required = _requires_change_scope_evidence(
        run.user_prompt,
        *(result.output for result in run.results),
    )
    baseline = _baseline_summary(run.git_baseline, _extract_prompt_paths(run.user_prompt))
    structured = _structured_security_verdict(run)
    phase_summary = "\n".join(
        f"- {result.role.value} attempt {result.attempt}: status={result.status}; "
        f"output={_shorten(result.output, limit=180)}"
        for result in run.results
    )
    return (
        "SecurityReviewContract: review only unresolved permission/security "
        "risks from structured evidence. Do not modify files. Do not ask for "
        "more context.\n\n"
        "Forbidden tools: do NOT call `todo_write`, `write_file`, `edit_file`, "
        "`apply_patch`, or `notebook_edit`. Your review must be grounded only "
        "in the task, run evidence, and your `git_status`/`git_diff` results. "
        "Do not mention files, tools, or artifacts not present in the task or "
        "real tool-call evidence.\n\n"
        f"{_change_scope_instruction(scope_required)}\n\n"
        f"baseline_summary: {baseline}\n"
        f"structured_security_verdict: {structured}\n"
        f"successful_tools: {', '.join(sorted(_run_successful_tools(run))) or 'none'}\n"
        f"content_readback_satisfied: {_run_has_expected_content_readback(run)}\n"
        f"scope_check_required: {scope_required}\n"
        "phase_summary:\n"
        f"{phase_summary}\n\n"
        f"{_evidence_rules()}\n\n"
        "If structured_security_verdict is PASS or WARN, do not claim missing "
        "git_status, git_diff, or content verification. Use that verdict unless "
        "you find a new concrete security issue in your own git_status/git_diff. "
        "If no implementer was selected, do not state that an implementer "
        "created, modified, or wrote files. If there is no real write-tool "
        "evidence, say there is insufficient evidence of filesystem writes.\n\n"
        f"{tool_evidence}\n\n"
        f"User task summary:\n{_shorten(run.user_prompt, limit=360)}"
    )


def _phase_final_text(result: SubAgentResult | None, *, fallback: str) -> str:
    if result is None:
        return fallback
    text = result.output or fallback
    if result.status == "completed" and text.startswith("PASS:"):
        return text.split("\n\n", 1)[0].strip()
    if result.status == "completed" and text.startswith("WARN:"):
        return text.split("\n\n", 1)[0].strip()
    return text


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
    implementation = run.latest_for(run.selected_coder_role) if run.selected_coder_role else None
    last_validation = run.latest_for(AgentRole.VALIDATOR)
    reviewer = run.latest_for(AgentRole.REVIEWER)
    security_reviewer = run.latest_for(AgentRole.SECURITY_REVIEWER)
    status = final_run_status(run)
    coder = (
        run.selected_coder_role.value
        if run.selected_coder_role
        else "none (implementation required but not executed)"
        if run.requires_write
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
    if reviewer is None:
        review_text = "No reviewer output was produced."
    elif reviewer.status == "hallucinated_output":
        review_text = (
            "[Review suppressed: the reviewer mentioned artifacts or tools not "
            "present in the task. The review may describe a different task. "
            "See the run trace for the original output.]"
        )
    else:
        review_text = _phase_final_text(
            reviewer,
            fallback="No reviewer output was produced.",
        )
    if security_reviewer is None:
        security_text = ""
    elif security_reviewer.status == "hallucinated_output":
        security_text = (
            "\n\nSecurity review: [suppressed — the security reviewer mentioned "
            "artifacts or tools not present in the task. See the run trace.]"
        )
    else:
        security_text = f"\n\nSecurity review:\n{_structured_security_verdict(run)}"
    validation_text = _phase_final_text(
        last_validation,
        fallback="No validation output was produced.",
    )
    implementation_text = (
        implementation.output if implementation else "No implementation output was produced."
    )
    if run.selected_coder_role is None:
        research_text = research.output if research else "No research output was produced."
        return (
            f"Multi-agent run finished with status: {status}\n"
            f"Selected implementer: {coder}\n\n"
            f"Research:\n{research_text}\n\n"
            f"Review:\n{review_text}"
            f"{security_text}"
        )
    return (
        f"Multi-agent run finished with status: {status}\n"
        f"Selected implementer: {coder}\n\n"
        f"Implementation:\n{implementation_text}\n\n"
        f"Validation:\n{validation_text}\n\n"
        f"Review:\n{review_text}"
        f"{security_text}"
        f"{evidence_note}"
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
    cfg = replace(config or AgentConfig(cwd="."), suppress_run_saved_message=True)
    if not cfg.approval_session_id:
        digest = hashlib.sha1(
            f"{cfg.cwd}\n{user_prompt}\n{datetime.now(UTC).isoformat()}".encode()
        ).hexdigest()[:12]
        cfg = replace(cfg, approval_session_id=f"multiagent-{digest}")
    state = MultiAgentRun(user_prompt=user_prompt)
    state.git_baseline = _capture_git_baseline(cfg.cwd)

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
            plan = _apply_role_guardrails(plan, state)
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
            research = _apply_role_guardrails(research, state)
            if subagent_blocked(research):
                _refresh_contract_validation(state, cfg)
                state.final_answer = synthesize_final_answer(state)
                return state.final_answer
            if "coder" not in planned_phases and research_discovered_write_requirement(
                user_prompt, plan, research
            ):
                promote_to_write_flow(state, planned_phases)
                if on_progress is None:
                    console.print(
                        "[cyan][multi-agent][/cyan] research discovered an "
                        "implementation requirement; promoting to coder + validator."
                    )

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
                _refresh_contract_validation(state, cfg)
                state.final_answer = synthesize_final_answer(state)
                return state.final_answer

            if "validator" in planned_phases:
                # Every planned flow that includes "validator" also includes
                # "planner" and "researcher", so those phases have already run
                # here and produced their results.
                assert plan is not None
                assert research is not None
                validation_contract = build_validation_contract(
                    user_prompt,
                    plan,
                    research,
                    implementation,
                    git_baseline=state.git_baseline,
                )
                validation_prompt = _build_validation_prompt(
                    user_prompt,
                    plan,
                    research,
                    implementation,
                    git_baseline=state.git_baseline,
                )
                validation_config = _validator_config_for_contract(
                    cfg,
                    validation_contract,
                )
                # Prefer deterministic evidence collection when the contract and
                # config allow it; otherwise run the validator subagent.
                if _can_use_deterministic_validation(
                    validation_contract,
                    validation_config,
                    implementation,
                ):
                    if on_progress:
                        on_progress("validator: collecting deterministic evidence")
                    else:
                        print(
                            "[multi-agent:validator] Collecting deterministic evidence...",
                            flush=True,
                        )
                    validation = _deterministic_validation_result(
                        validation_contract,
                        validation_prompt,
                        validation_config,
                        implementation,
                    )
                    state.add_result(validation)
                    if not on_progress:
                        console.print("[green][multi-agent][/green] completed validator")
                else:
                    validation = _execute_phase(
                        state,
                        AgentRole.VALIDATOR,
                        validation_prompt,
                        selection,
                        validation_config,
                        on_progress=on_progress,
                    )
                validation = _finalize_if_evidence_satisfied(
                    validation,
                    required_tools=set(validation_contract.required_evidence_tools) - {"bash"},
                    verdict="PASS: required validation evidence tools completed successfully.",
                )
                validation = _enforce_change_scope_evidence(
                    validation,
                    required=_requires_change_scope_evidence(
                        user_prompt,
                        plan.output if plan else None,
                    ),
                )
                validation = _apply_role_guardrails(validation, state)
                # A blocked/confused validator is advisory — keep the run going
                # to the reviewer and final synthesis instead of discarding the
                # implementation. Only a genuine validation *failure* (below)
                # triggers the repair loop.

                repair_attempt = 0
                while (
                    validation_failed(validation)
                    and should_repair_with_coder(validation)
                    and repair_attempt < max_repair_attempts
                ):
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
                        _refresh_contract_validation(state, cfg)
                        state.final_answer = synthesize_final_answer(state)
                        return state.final_answer

                    validation_contract = build_validation_contract(
                        user_prompt,
                        plan,
                        research,
                        implementation,
                        git_baseline=state.git_baseline,
                    )
                    validation_prompt = _build_validation_prompt(
                        user_prompt,
                        plan,
                        research,
                        implementation,
                        git_baseline=state.git_baseline,
                    )
                    validation_config = _validator_config_for_contract(
                        cfg,
                        validation_contract,
                    )
                    if _can_use_deterministic_validation(
                        validation_contract,
                        validation_config,
                        implementation,
                    ):
                        if on_progress:
                            on_progress("validator: collecting deterministic evidence")
                        else:
                            print(
                                "[multi-agent:validator] Collecting deterministic evidence...",
                                flush=True,
                            )
                        validation = _deterministic_validation_result(
                            validation_contract,
                            validation_prompt,
                            validation_config,
                            implementation,
                        )
                        validation.attempt = repair_attempt + 1
                        state.add_result(validation)
                        if not on_progress:
                            console.print("[green][multi-agent][/green] completed validator")
                    else:
                        validation = _execute_phase(
                            state,
                            AgentRole.VALIDATOR,
                            validation_prompt,
                            selection,
                            validation_config,
                            attempt=repair_attempt + 1,
                            on_progress=on_progress,
                        )
                    validation = _finalize_if_evidence_satisfied(
                        validation,
                        required_tools=set(validation_contract.required_evidence_tools) - {"bash"},
                        verdict="PASS: required validation evidence tools completed successfully.",
                    )
                    validation = _enforce_change_scope_evidence(
                        validation,
                        required=_requires_change_scope_evidence(
                            user_prompt,
                            plan.output if plan else None,
                        ),
                    )
                    validation = _apply_role_guardrails(validation, state)
                    if subagent_blocked(validation):
                        # Validator gave up mid-repair: stop retrying, but still
                        # review and synthesize what the coder produced.
                        break

        if "reviewer" in planned_phases:
            review_prompt = _build_review_prompt(state)
            review_scope_required = _requires_change_scope_evidence(
                state.user_prompt,
                *(result.output for result in state.results),
            )
            review_config = _reviewer_config_for_scope(
                cfg,
                scope_required=review_scope_required,
            )
            if review_scope_required and _git_scope_tools_available(review_config.cwd):
                if on_progress:
                    on_progress("reviewer: collecting deterministic scope evidence")
                else:
                    print(
                        "[multi-agent:reviewer] Collecting deterministic scope evidence...",
                        flush=True,
                    )
                review = _deterministic_scope_review_result(
                    AgentRole.REVIEWER,
                    review_prompt,
                    review_config,
                    verdict=("PASS: required review scope evidence tools completed successfully."),
                    prior_results=state.results,
                )
                state.add_result(review)
                if not on_progress:
                    console.print("[green][multi-agent][/green] completed reviewer")
            else:
                review = _execute_phase(
                    state,
                    AgentRole.REVIEWER,
                    review_prompt,
                    selection,
                    review_config,
                    on_progress=on_progress,
                )
            review = _finalize_if_evidence_satisfied(
                review,
                required_tools={"git_status", "git_diff"} if review_scope_required else set(),
                verdict="PASS: required review scope evidence tools completed successfully.",
            )
            review = _enforce_change_scope_evidence(
                review,
                required=review_scope_required,
            )
            review = _apply_role_guardrails(review, state)
            if subagent_blocked(review):
                _refresh_contract_validation(state, cfg)
                state.final_answer = synthesize_final_answer(state)
                return state.final_answer

            if should_run_security_review(state):
                security_prompt = _build_security_review_prompt(state)
                security_scope_required = _requires_change_scope_evidence(
                    state.user_prompt,
                    *(result.output for result in state.results),
                )
                security_config = _reviewer_config_for_scope(
                    cfg,
                    scope_required=security_scope_required,
                )
                if security_scope_required and _git_scope_tools_available(security_config.cwd):
                    if on_progress:
                        on_progress("security_reviewer: collecting deterministic scope evidence")
                    else:
                        print(
                            "[multi-agent:security_reviewer] Collecting deterministic scope evidence...",
                            flush=True,
                        )
                    security_review = _deterministic_scope_review_result(
                        AgentRole.SECURITY_REVIEWER,
                        security_prompt,
                        security_config,
                        verdict=(
                            "PASS: required security scope evidence tools completed successfully."
                        ),
                        prior_results=state.results,
                    )
                    state.add_result(security_review)
                    if not on_progress:
                        console.print("[green][multi-agent][/green] completed security_reviewer")
                else:
                    security_review = _execute_phase(
                        state,
                        AgentRole.SECURITY_REVIEWER,
                        security_prompt,
                        selection,
                        security_config,
                        on_progress=on_progress,
                    )
                security_review = _finalize_if_evidence_satisfied(
                    security_review,
                    required_tools={"git_status", "git_diff"} if security_scope_required else set(),
                    verdict="PASS: required security scope evidence tools completed successfully.",
                )
                security_review = _enforce_change_scope_evidence(
                    security_review,
                    required=security_scope_required,
                )
                security_review = _apply_role_guardrails(security_review, state)
                if subagent_blocked(security_review):
                    _refresh_contract_validation(state, cfg)
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

        _refresh_contract_validation(state, cfg)
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
        _refresh_contract_validation(state, cfg)
        if run_log and run_log.run_dir is not None:
            _persist_multiagent_parent_run(
                run_log.run_dir,
                state,
                selection,
                cfg,
                started_at=started_at,
                ended_at=ended_at,
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
            console.print(f"[dim]Multi-agent run saved: {run_log.run_dir}[/dim]")
