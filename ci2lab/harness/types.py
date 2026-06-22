"""Internal harness types (not part of the public contract)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

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

    confirm_callback: Callable[[str, str], bool] | None = None

    run_log_enabled: bool = True
    """Persist run artifacts in runs/."""

    runs_dir: str = "runs"
    """Base directory for run logs."""

    config_snapshot: dict[str, Any] | None = None
    """Effective config for config_snapshot.json (without secrets)."""

    write_tools_enabled: bool = True
    """If False, write_file and edit_file return an error without executing."""

    require_diff_preview: bool = True
    """If True, write/edit always show a diff and ask for confirmation (--yes does not skip)."""

    verify_completion: bool = False
    """If True, after the agent reports a task done AND effectful work happened
    this turn, a fresh read-only subagent verifies the result against the
    original request; on failure the agent is asked to fix it. Opt-in: on weak
    local models the verifier can false-reject, so it stays off by default."""

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
