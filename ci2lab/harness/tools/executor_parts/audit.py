"""Audit logging helpers for tool execution decisions."""

from __future__ import annotations

from typing import Any

from ci2lab.harness.types import AgentConfig
from ci2lab.security.audit import (
    AuditPersistContext,
    get_audit_persist_context,
    log_decision,
    set_audit_persist_context,
)
from ci2lab.security.engine import ToolGateResult


def ensure_audit_persist_context(config: AgentConfig) -> None:
    """Install the audit persistence context for this run if not already set.

    Idempotent: if a context is already registered it is left untouched so the
    first caller wins for the duration of the process.

    Args:
        config: Active agent configuration providing the workspace, runs
            directory and security engine used to persist audit decisions.
    """
    if get_audit_persist_context() is not None:
        return
    set_audit_persist_context(
        AuditPersistContext(
            workspace=config.cwd,
            runs_dir=config.runs_dir,
            security_engine=config.security_engine,
        )
    )


def audit_security_decision(
    *,
    tool: str,
    detail: str,
    decision: str,
    gate: ToolGateResult | None = None,
    reason: str | None = None,
    confirmed: bool | None = None,
    outcome: str | None = None,
    confirm_extra: dict[str, Any] | None = None,
) -> None:
    """Record a single tool security decision in the audit log.

    Merges the supplied fields with any metadata available on ``gate`` (engine,
    matched rule, guard flags, session-approval details) and forwards the
    combined record to :func:`log_decision`.

    Args:
        tool: Name of the tool the decision applies to.
        detail: Human-readable summary of the action (e.g. the target path).
        decision: Decision verb such as ``"allow"``, ``"deny"`` or ``"ask"``.
        gate: Gate result whose metadata enriches the audit record, if any.
        reason: Explicit reason; falls back to ``gate.reason`` when omitted.
        confirmed: Whether the user confirmed the action, if applicable.
        outcome: Final outcome label for the decision.
        confirm_extra: Additional confirmation metadata to attach to the record.
    """
    kwargs: dict[str, Any] = {
        "tool": tool,
        "detail": detail,
        "decision": decision,
        "reason": reason or (gate.reason if gate else ""),
        "confirmed": confirmed,
        "outcome": outcome,
    }
    extra = dict(confirm_extra or {})
    if gate is not None:
        kwargs.update(
            {
                "security_engine": gate.engine,
                "matched_rule": gate.matched_rule,
                "external_directory": gate.external_directory,
                "hard_guards_enabled": gate.hard_guards_enabled,
                "permission_layer_enabled": gate.permission_layer_enabled,
                "experimental": gate.experimental,
                "session_approval_used": gate.session_approval_used,
                "session_approval_scope": gate.session_approval_scope,
            }
        )
        extra.setdefault("engine", gate.engine)
    if extra:
        kwargs["extra"] = extra
    log_decision(**kwargs)
