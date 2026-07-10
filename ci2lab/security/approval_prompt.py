"""Interactive approval prompt for permission-layer security engines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ci2lab.console import active_progress
from ci2lab.harness.types import AgentConfig
from ci2lab.security.audit import get_audit_persist_context
from ci2lab.security.engine import ToolGateResult, normalize_security_engine, uses_permission_layer
from ci2lab.security.session_permissions import (
    build_approval_fingerprint,
    grant_session_approval,
    resolve_session_key,
)

InputFunc = Callable[[str], str]
OutputFunc = Callable[[str], None]


class ApprovalChoice(str, Enum):
    """User choice returned by the interactive approval prompt.

    Attributes:
        ALLOW_ONCE: Allow this single call only.
        ALLOW_SESSION: Allow this and matching calls for the session.
        DENY_ONCE: Deny this single call.
        ABORT: Cancel execution entirely.
    """

    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    DENY_ONCE = "deny_once"
    ABORT = "abort"


@dataclass(frozen=True)
class OpenCodeApprovalDecision:
    """Context shown to the user when a permission evaluation returns ``ask``.

    Attributes:
        tool_name: Name of the tool awaiting approval.
        target_summary: Short summary of the tool's target.
        matched_rule: Identifier of the rule that triggered the ask.
        reason: Machine-readable reason code for the ask.
        external_directory: True if the target lies outside the workspace.
    """

    tool_name: str
    target_summary: str
    matched_rule: str | None = None
    reason: str = ""
    external_directory: bool = False


@dataclass(frozen=True)
class OpenCodeConfirmResult:
    """Outcome of resolving a permission-layer ``ask`` confirmation.

    Attributes:
        proceed: True if the tool may run.
        choice: The user's approval choice, if a prompt was shown.
        reason: Machine-readable reason code for the outcome.
        message: Optional human-readable message (e.g. on abort/deny).
        session_scope_granted: Scope granted for the session, if any.
    """

    proceed: bool
    choice: ApprovalChoice | None = None
    reason: str = ""
    message: str | None = None
    session_scope_granted: str | None = None


_CHOICE_ALIASES: dict[str, ApprovalChoice] = {
    "a": ApprovalChoice.ALLOW_ONCE,
    "1": ApprovalChoice.ALLOW_ONCE,
    "once": ApprovalChoice.ALLOW_ONCE,
    "allow_once": ApprovalChoice.ALLOW_ONCE,
    "s": ApprovalChoice.ALLOW_SESSION,
    "2": ApprovalChoice.ALLOW_SESSION,
    "session": ApprovalChoice.ALLOW_SESSION,
    "allow_session": ApprovalChoice.ALLOW_SESSION,
    "d": ApprovalChoice.DENY_ONCE,
    "3": ApprovalChoice.DENY_ONCE,
    "deny": ApprovalChoice.DENY_ONCE,
    "deny_once": ApprovalChoice.DENY_ONCE,
    "c": ApprovalChoice.ABORT,
    "q": ApprovalChoice.ABORT,
    "n": ApprovalChoice.ABORT,
    "abort": ApprovalChoice.ABORT,
    "cancel": ApprovalChoice.ABORT,
}


def parse_approval_choice(raw: str) -> ApprovalChoice:
    """Parse a raw user input string into an :class:`ApprovalChoice`.

    Args:
        raw: Raw text entered by the user.

    Returns:
        The matching :class:`ApprovalChoice`.

    Raises:
        ValueError: If the input does not map to a known choice.
    """
    key = raw.strip().lower()
    if key in _CHOICE_ALIASES:
        return _CHOICE_ALIASES[key]
    raise ValueError(f"unrecognized approval option: {raw!r}")


def prompt_opencode_approval(
    decision: OpenCodeApprovalDecision,
    *,
    security_engine: str = "opencode_experimental",
    input_func: InputFunc = input,
    output_func: OutputFunc = print,
) -> ApprovalChoice:
    """Show an OpenCode-style approval menu and return the user's choice.

    Options: allow once, allow session, deny once, abort.

    Args:
        decision: Context describing the pending tool call.
        security_engine: Engine name shown in the prompt header.
        input_func: Callable used to read user input (injectable for tests).
        output_func: Callable used to render prompt lines.

    Returns:
        The selected :class:`ApprovalChoice` (``ABORT`` on EOF or empty input).
    """
    engine = normalize_security_engine(security_engine)
    output_func("")
    output_func(f"[{engine}] Permission required (ask)")
    output_func(f"  tool: {decision.tool_name}")
    output_func(f"  target: {decision.target_summary}")
    if decision.matched_rule:
        output_func(f"  rule: {decision.matched_rule}")
    if decision.external_directory:
        output_func("  external_directory: true")
    if decision.reason:
        output_func(f"  reason: {decision.reason}")
    output_func("")
    output_func("  [a] Allow once   [s] Allow session   [d] Deny once   [c] Cancel")
    try:
        # Pause the "thinking" spinner so it doesn't repaint over this prompt
        # and block the user from answering.
        with active_progress.suspended():
            raw = input_func("Choice [a/s/d/c]: ")
    except EOFError:
        return ApprovalChoice.ABORT
    if not raw.strip():
        return ApprovalChoice.ABORT
    return parse_approval_choice(raw)


def is_opencode_experimental_engine(security_engine: str) -> bool:
    """Return whether the engine is exactly ``opencode_experimental``."""
    return normalize_security_engine(security_engine) == "opencode_experimental"


def uses_modern_permission_prompt(security_engine: str) -> bool:
    """Return whether the engine uses the modern permission-layer prompt."""
    return uses_permission_layer(security_engine)


def confirm_opencode_ask(
    *,
    config: AgentConfig,
    tool_name: str,
    args: dict[str, Any],
    gate: ToolGateResult,
    detail: str,
    input_func: InputFunc = input,
    output_func: OutputFunc = print,
) -> OpenCodeConfirmResult:
    """Resolve a permission-layer ``ask`` via prompt, auto-confirm or session.

    Applies to the opencode_experimental and ci2lab_guard engines.

    Args:
        config: Active agent configuration (selects the engine).
        tool_name: Name of the tool awaiting approval.
        args: Arguments passed to the tool.
        gate: Gate result that produced the ``ask``.
        detail: Short summary of the tool's target for the prompt.
        input_func: Callable used to read user input (injectable for tests).
        output_func: Callable used to render prompt lines.

    Returns:
        The :class:`OpenCodeConfirmResult` describing the resolution.

    Raises:
        ValueError: If the engine does not use a permission layer.
    """
    engine = normalize_security_engine(config.security_engine)
    if not uses_permission_layer(engine):
        raise ValueError(
            "confirm_opencode_ask only applies to engines with a permission layer "
            "(opencode_experimental, ci2lab_guard)"
        )

    if config.auto_confirm:
        return OpenCodeConfirmResult(proceed=True, reason="auto_confirm")

    if gate.session_approval_used:
        return OpenCodeConfirmResult(
            proceed=True,
            reason=gate.reason or "session_allow",
            session_scope_granted=gate.session_approval_scope,
        )

    prompt_ctx = OpenCodeApprovalDecision(
        tool_name=tool_name,
        target_summary=detail,
        matched_rule=gate.matched_rule,
        reason=gate.reason,
        external_directory=gate.external_directory,
    )
    choice = prompt_opencode_approval(
        prompt_ctx,
        security_engine=engine,
        input_func=input_func,
        output_func=output_func,
    )

    ctx = get_audit_persist_context()
    session_key = resolve_session_key(
        session_id=config.approval_session_id or config.session_id,
        run_id=ctx.run_id if ctx else None,
    )
    fingerprint = build_approval_fingerprint(
        engine=engine,
        tool_name=tool_name,
        args=args,
        matched_rule=gate.matched_rule,
        external_directory=gate.external_directory,
    )

    if choice is ApprovalChoice.ABORT:
        return OpenCodeConfirmResult(
            proceed=False,
            choice=choice,
            reason="user_abort",
            message=f"Execution cancelled by the user (`{tool_name}`).",
        )

    if choice is ApprovalChoice.DENY_ONCE:
        if session_key:
            grant_session_approval(session_key, fingerprint, "deny_once")
        return OpenCodeConfirmResult(
            proceed=False,
            choice=choice,
            reason="user_deny_once",
            message=f"Denied once (`{tool_name}`).",
            session_scope_granted="deny_once",
        )

    if choice is ApprovalChoice.ALLOW_SESSION:
        if session_key:
            grant_session_approval(session_key, fingerprint, "allow_session")
        return OpenCodeConfirmResult(
            proceed=True,
            choice=choice,
            reason="user_allow_session",
            session_scope_granted="allow_session",
        )

    # ALLOW_ONCE: only this call, no session cache.
    return OpenCodeConfirmResult(
        proceed=True,
        choice=ApprovalChoice.ALLOW_ONCE,
        reason="user_allow_once",
    )
