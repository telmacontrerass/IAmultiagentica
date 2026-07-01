"""Internal harness types (not part of the public contract)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ci2lab.harness.token_usage import TokenUsageState

if TYPE_CHECKING:
    from ci2lab.contracts.types import ModelSelection
    from ci2lab.security.opencode_permissions import OpenCodePermissionConfig
    from ci2lab.settings import ToolSettings


@dataclass(frozen=True)
class ToolCall:
    """Normalized tool call (native or parsed)."""

    name: str
    arguments: dict[str, Any]
    call_id: str | None = None


@dataclass
class ToolResult:
    """Result of executing a tool."""

    tool_name: str
    content: str
    is_error: bool = False
    call_id: str | None = None
    outcome: str | None = None
    """approved | denied | blocked_by_config | blocked_by_security_profile | failed"""


@dataclass
class AgentConfig:
    """Configuration for a harness run."""

    cwd: str
    max_rounds: int = 25
    max_tool_output_chars: int = 10_000
    bash_timeout_seconds: int = 60
    auto_confirm: bool = False
    stream: bool = True
    """Show model tokens in real time."""

    session_id: str | None = None
    """If set, persists the history at the end of each turn."""

    approval_session_id: str | None = None
    """In-memory permission approval scope for one run.

    Unlike session_id, this must not imply chat/session persistence. Multi-agent
    subagents use it so an "allow session" decision survives phase/attempt
    boundaries inside the same orchestrated run without leaking to later runs.
    """

    project_id: str | None = None
    """Optional UI knowledge-project identifier associated with the session."""

    multiagent_flow: str | None = None
    """Optional explicit multi-agent flow selector (e.g. "paper_review"). When
    set, the orchestrator runs that flow instead of inferring one from the prompt."""

    researcher_id: str | None = None
    """Optional researcher-profile id whose field/style the review adapts to."""

    confirm_callback: Callable[[str, str], bool] | None = None

    run_log_enabled: bool = True
    """Persist run artifacts in runs/."""

    suppress_run_saved_message: bool = False
    """If True, persist run artifacts without printing the final run path."""

    runs_dir: str = "runs"
    """Base directory for run logs."""

    config_snapshot: dict[str, Any] | None = None
    """Effective config for config_snapshot.json (without secrets)."""

    write_tools_enabled: bool = True
    """If False, write_file and edit_file return an error without executing."""

    require_diff_preview: bool = True
    """If True, write/edit always show a diff and ask for confirmation (--yes does not skip)."""

    verify_completion: bool = False
    """If True, after the agent reports a task done AND verifiable work happened
    this turn (a mutation, or it ran commands/tests), a fresh subagent derives
    the acceptance criteria from the original request and checks the result
    against reality; on a confident, actionable failure the agent is asked to fix
    it and keeps trying. See ``harness.query.verifier``.

    This dataclass default is False so direct constructors (tests, benchmarks,
    security/redteam audits) opt in explicitly. The *product* enables it by
    default: real runs build the config from ``Ci2LabConfig.verify_completion``
    (``DEFAULT_VERIFY_COMPLETION``), so an ordinary CLI/UI user gets completion
    verification with no setting to flip. It is deliberately conservative (leans
    PASS when unsure), so a weak local model is not trapped in a false-reject
    loop."""

    verify_final_answer: bool = True
    """If True, every final answer is checked against deterministic evidence
    collected during the turn before it is returned to the user. Claims about
    current facts, files, commands, sources, URLs, or workspace mutations must
    be grounded in the prompt or successful tool results."""

    security_profile: str = "standard"
    """Security profile (strict, standard, dev, audit)."""

    security_engine: str = "claude_experimental"
    """Security engine: claude_experimental (default), ci2lab (legacy) or opencode_experimental."""

    opencode_permissions: OpenCodePermissionConfig | None = None
    """OpenCode-style permission rules (experimental engine only)."""

    skill_allowed_tools: frozenset[str] | None = None
    """When set by an invoked skill, only these tool names are exposed to the model."""

    role_anchor: str | None = None
    """English role-discipline anchor reinjected for subagents after tool rounds."""

    required_evidence_tools: frozenset[str] | None = None
    """When set, stop the agent turn once these tools have succeeded.

    Used by compact validation/review phases so a small model cannot keep
    iterating after the harness already has the required evidence.
    """

    evidence_completion_verdict: str | None = None
    """Deterministic final text used when required_evidence_tools are satisfied."""

    selection: ModelSelection | None = None
    """Active model selection. Set by run_agent so tools (e.g. `delegate`) can
    spawn a subagent with the same model. Not part of the persisted config."""

    delegation_depth: int = 0
    """How deep this run is in the delegate-subagent chain. 0 = top-level agent.
    Bounds recursion: a subagent at the max depth cannot delegate again."""

    cancellation_event: Any | None = None
    """Optional threading.Event-like object used to stop an in-flight run."""

    last_run_dir: str | None = None
    """Latest run directory produced by RunLogger for this config instance."""

    tool_settings: ToolSettings | None = None
    """allow/deny rules from settings.json (merged global + project).
    If None, no settings rules are applied and everything is permitted."""

    token_usage: TokenUsageState = field(default_factory=TokenUsageState)
    """Token counters for the current turn and session."""

    vision_model: str = ""
    """Ollama tag of the fallback vision model (e.g. 'llava', 'qwen3-vl').
    Empty = use the main model when it is vision-capable; otherwise image
    analysis is unavailable unless the agent calls analyze_image explicitly."""

    vision_enabled: bool = True
    """If False, image_paths are ignored and analyze_image tool returns a
    disabled message."""

    image_paths: list[str] = field(default_factory=list)
    """Image files to attach to the first user message.  Forwarded natively as
    base64 image_url blocks when the main model is vision-capable; otherwise
    each image is described by the fallback vision_model and the description is
    injected into the prompt text."""
