"""State types for multi-agent orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

EVIDENCE_SCHEMA_VERSION = "evidence.v1"
CONTRACT_VALIDATION_SCHEMA_VERSION = "contract_validation.v1"
FAILURE_CLASSIFICATION_SCHEMA_VERSION = "failure_classification.v1"


def _evidence_target_path(arguments: dict[str, Any]) -> str | None:
    for key in ("path", "source", "output", "file", "target"):
        value = arguments.get(key)
        if value:
            return str(value)
    return None


def _evidence_hash(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AgentRole(str, Enum):
    """Predefined subagent roles supported by the orchestrator."""

    PLANNER = "planner"
    RESEARCHER = "researcher"
    PYTHON_CODER = "python_coder"
    FRONTEND_CODER = "frontend_coder"
    TEST_CODER = "test_coder"
    DOCS_CODER = "docs_coder"
    GENERALIST_CODER = "generalist_coder"
    VALIDATOR = "validator"
    REVIEWER = "reviewer"
    SECURITY_REVIEWER = "security_reviewer"
    # Scientific peer-review lenses. All read-only and grounded: every claim must
    # be backed by a verbatim manuscript quote or a verifiable absence/external
    # reference (see ci2lab/harness/multiagent/grounding.py).
    INTAKE_REVIEWER = "intake_reviewer"
    SCOPE_REVIEWER = "scope_reviewer"
    NOVELTY_REVIEWER = "novelty_reviewer"
    METHODOLOGY_REVIEWER = "methodology_reviewer"
    FIELD_EXPERT_REVIEWER = "field_expert_reviewer"
    ADVERSARIAL_REVIEWER = "adversarial_reviewer"
    FORMAT_REVIEWER = "format_reviewer"
    GROUNDEDNESS_VERIFIER = "groundedness_verifier"
    REVISION_PLANNER = "revision_planner"


@dataclass(frozen=True)
class EvidenceEntry:
    """Versioned evidence record derived from a phase tool-call trace."""

    role: str
    phase: str
    tool: str
    ok: bool
    args: dict[str, Any] = field(default_factory=dict)
    target_path: str | None = None
    outcome: str | None = None
    output_preview: str | None = None
    output_hash: str | None = None
    error_preview: str | None = None
    source_run: str | None = None
    timestamp: str | None = None
    failure_class: str | None = None
    schema_version: str = EVIDENCE_SCHEMA_VERSION

    @classmethod
    def from_tool_call(
        cls,
        entry: dict[str, Any],
        *,
        role: AgentRole | str,
        phase: AgentRole | str | None = None,
        source_run: str | None = None,
    ) -> EvidenceEntry:
        """Build EvidenceEntry v1 from an existing tool-call dictionary."""
        arguments = entry.get("arguments")
        args = dict(arguments) if isinstance(arguments, dict) else {}
        output_preview = str(entry.get("output_preview") or entry.get("output") or "")
        error_preview = entry.get("error_preview") or entry.get("error")
        phase_value = phase.value if isinstance(phase, AgentRole) else phase
        role_value = role.value if isinstance(role, AgentRole) else role
        return cls(
            role=str(role_value),
            phase=str(phase_value or role_value),
            tool=str(entry.get("tool") or ""),
            ok=bool(entry.get("ok")),
            args=args,
            target_path=_evidence_target_path(args),
            outcome=str(entry["outcome"]) if entry.get("outcome") is not None else None,
            output_preview=output_preview or None,
            output_hash=_evidence_hash(output_preview),
            error_preview=str(error_preview) if error_preview else None,
            source_run=source_run,
            timestamp=str(entry.get("started_at") or entry.get("timestamp") or "") or None,
            failure_class=str(entry["failure_class"])
            if entry.get("failure_class") is not None
            else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this evidence entry for trace JSON."""
        return {
            "schema_version": self.schema_version,
            "role": self.role,
            "phase": self.phase,
            "tool": self.tool,
            "ok": self.ok,
            "args": self.args,
            "target_path": self.target_path,
            "outcome": self.outcome,
            "output_preview": self.output_preview,
            "output_hash": self.output_hash,
            "error_preview": self.error_preview,
            "source_run": self.source_run,
            "timestamp": self.timestamp,
            "failure_class": self.failure_class,
        }


@dataclass(frozen=True)
class ContractValidation:
    """Versioned, advisory contract-validation record for run traces."""

    kind: str
    status: str
    expected_artifacts: list[dict[str, Any]] = field(default_factory=list)
    observed_artifacts: list[dict[str, Any]] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    observed_evidence: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    allowed_write_paths: list[str] = field(default_factory=list)
    allowed_write_roots: list[str] = field(default_factory=list)
    observed_changed_paths: list[str] = field(default_factory=list)
    scope_status: str | None = None
    scope_failures: list[str] = field(default_factory=list)
    schema_version: str = CONTRACT_VALIDATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialize this contract-validation record for trace JSON."""
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "status": self.status,
            "expected_artifacts": self.expected_artifacts,
            "observed_artifacts": self.observed_artifacts,
            "required_evidence": self.required_evidence,
            "observed_evidence": self.observed_evidence,
            "missing_evidence": self.missing_evidence,
            "failures": self.failures,
            "notes": self.notes,
            "allowed_write_paths": self.allowed_write_paths,
            "allowed_write_roots": self.allowed_write_roots,
            "observed_changed_paths": self.observed_changed_paths,
            "scope_status": self.scope_status,
            "scope_failures": self.scope_failures,
        }


@dataclass(frozen=True)
class FailureClassification:
    """Versioned failure taxonomy record for multi-agent traces."""

    status: str
    failure_class: str
    failure_reason: str
    failed_phase: str | None = None
    repairable: bool = False
    related_evidence: list[str] = field(default_factory=list)
    contract_kind: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    schema_version: str = FAILURE_CLASSIFICATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialize this failure classification for trace JSON."""
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "failure_class": self.failure_class,
            "failure_reason": self.failure_reason,
            "failed_phase": self.failed_phase,
            "repairable": self.repairable,
            "related_evidence": self.related_evidence,
            "contract_kind": self.contract_kind,
            "details": self.details,
        }


@dataclass
class SubAgentResult:
    """Result produced by a subagent with its own isolated context."""

    role: AgentRole
    task: str
    output: str
    status: str = "completed"
    attempt: int = 1
    error: str | None = None
    role_anchor: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    can_write: bool | None = None
    input_prompt: str | None = None
    subagent_run_dir: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int | None = None
    rounds: int | None = None
    skipped_reason: str | None = None


@dataclass
class MultiAgentRun:
    """Shared orchestration state, controlled only by the orchestrator."""

    user_prompt: str
    results: list[SubAgentResult] = field(default_factory=list)
    selected_coder_role: AgentRole | None = None
    final_answer: str | None = None
    failed_phase: str | None = None
    error: str | None = None
    contract_validation: ContractValidation | None = None
    failure_classification: FailureClassification | None = None
    # Pre-orchestration intent routing (legacy backbone, set by
    # classify_multiagent_intent).
    intent: str | None = None
    requires_write: bool | None = None
    planned_phases: list[str] = field(default_factory=list)
    intent_reason: str | None = None
    intent_confidence: str | None = None
    # Rich orchestration decision (advisory, set by
    # classify_orchestration_decision). These never grant permission; the
    # execution gate remains the source of truth.
    task_type: str | None = None
    required_capabilities: list[str] = field(default_factory=list)
    risk_level: str | None = None
    needs_confirmation: bool | None = None
    decision_reasons: list[str] = field(default_factory=list)
    # Snapshot of `git status --short` captured before the run starts.
    # Used by validation and review prompts to distinguish pre-existing WIP
    # from changes introduced by the current run.
    git_baseline: str | None = None

    def add_result(self, result: SubAgentResult) -> None:
        """Append a subagent result to the run's ordered result list."""
        self.results.append(result)

    def latest_for(self, role: AgentRole) -> SubAgentResult | None:
        """Return the most recent result for ``role``, or ``None`` if it never ran.

        Args:
            role: The subagent role to look up.

        Returns:
            The latest :class:`SubAgentResult` produced by ``role``, or ``None``.
        """
        for result in reversed(self.results):
            if result.role == role:
                return result
        return None
