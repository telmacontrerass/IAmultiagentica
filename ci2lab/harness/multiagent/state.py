"""State types for multi-agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
