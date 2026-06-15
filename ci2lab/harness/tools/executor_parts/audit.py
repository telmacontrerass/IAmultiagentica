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

