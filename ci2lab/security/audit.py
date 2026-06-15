"""Registro de decisiones de seguridad (memoria + JSONL persistido)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ci2lab.security.paths import resolve_workspace_path


@dataclass(frozen=True)
class SecurityAuditEntry:
    timestamp: str
    tool: str
    detail: str
    decision: str
    reason: str
    confirmed: bool | None = None
    outcome: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditPersistContext:
    workspace: str
    runs_dir: str = "runs"
    run_id: str | None = None
    run_subdir: str | None = None
    security_engine: str = "claude_experimental"


_audit_log: list[SecurityAuditEntry] = []
_persist_context: AuditPersistContext | None = None


def set_audit_persist_context(ctx: AuditPersistContext | None) -> None:
    global _persist_context
    _persist_context = ctx


def get_audit_persist_context() -> AuditPersistContext | None:
    return _persist_context


def _audit_jsonl_path(ctx: AuditPersistContext) -> Path:
    workspace = Path(ctx.workspace).resolve()
    if ctx.run_subdir:
        target = workspace / ctx.runs_dir / ctx.run_subdir / "security_audit.jsonl"
    else:
        target = workspace / ".ci2lab" / "security_audit.jsonl"
    resolved = target.resolve()
    resolved.relative_to(workspace)
    return resolved


def _persist_line(record: dict[str, Any]) -> None:
    if _persist_context is None:
        return
    try:
        path = _audit_jsonl_path(_persist_context)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, ValueError):
        pass


def log_decision(
    *,
    tool: str,
    detail: str,
    decision: str,
    reason: str,
    confirmed: bool | None = None,
    outcome: str | None = None,
    extra: dict[str, Any] | None = None,
    security_engine: str | None = None,
    matched_rule: str | None = None,
    external_directory: bool | None = None,
    hard_guards_enabled: bool | None = None,
    permission_layer_enabled: bool | None = None,
    experimental: bool | None = None,
    run_id: str | None = None,
    session_approval_used: bool | None = None,
    session_approval_scope: str | None = None,
) -> SecurityAuditEntry:
    from ci2lab.security.engine import (
        enforce_ci2lab_hard_policy,
        is_experimental_engine,
        normalize_security_engine,
        uses_permission_layer,
    )

    engine = normalize_security_engine(
        security_engine
        or (_persist_context.security_engine if _persist_context else "claude_experimental")
    )
    hard = (
        hard_guards_enabled
        if hard_guards_enabled is not None
        else enforce_ci2lab_hard_policy(engine)
    )
    perm_layer = (
        permission_layer_enabled
        if permission_layer_enabled is not None
        else uses_permission_layer(engine)
    )
    is_experimental = (
        experimental
        if experimental is not None
        else is_experimental_engine(engine)
    )
    ext = external_directory if external_directory is not None else False

    session_used = session_approval_used if session_approval_used is not None else False
    entry = SecurityAuditEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        tool=tool,
        detail=detail,
        decision=decision,
        reason=reason,
        confirmed=confirmed,
        outcome=outcome,
        extra={
            **(extra or {}),
            "security_engine": engine,
            "matched_rule": matched_rule,
            "external_directory": ext,
            "hard_guards_enabled": hard,
            "permission_layer_enabled": perm_layer,
            "experimental": is_experimental,
            "session_approval_used": session_used,
            "session_approval_scope": session_approval_scope,
        },
    )
    _audit_log.append(entry)

    exec_outcome = outcome or ("executed" if decision == "allow" else "blocked")
    approval_choice = (extra or {}).get("approval_choice")
    record = {
        "timestamp": entry.timestamp,
        "run_id": run_id or (_persist_context.run_id if _persist_context else None),
        "security_engine": engine,
        "tool": tool,
        "target": detail,
        "decision": decision,
        "reason": reason,
        "matched_rule": matched_rule,
        "external_directory": ext,
        "hard_guards_enabled": hard,
        "permission_layer_enabled": perm_layer,
        "confirmed": confirmed,
        "outcome": exec_outcome,
        "experimental": is_experimental,
        "session_approval_used": session_used,
        "session_approval_scope": session_approval_scope,
    }
    if approval_choice is not None:
        record["approval_choice"] = approval_choice
    _persist_line(record)
    return entry


def get_audit_log() -> list[SecurityAuditEntry]:
    return list(_audit_log)


def clear_audit_log() -> None:
    _audit_log.clear()


def resolve_audit_path_within_workspace(
    workspace: str,
    *,
    runs_dir: str = "runs",
    run_subdir: str | None = None,
) -> Path:
    ctx = AuditPersistContext(
        workspace=workspace,
        runs_dir=runs_dir,
        run_subdir=run_subdir,
    )
    return _audit_jsonl_path(ctx)
