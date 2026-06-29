"""Ci2Lab core security and permissions layer.

Engines: `ci2lab` (default), `claude_experimental`, `opencode_experimental`.
The harness applies the gate via `harness/tools/executor.py` based on `AgentConfig.security_engine`.
"""

from ci2lab.security.audit import SecurityAuditEntry, clear_audit_log, get_audit_log, log_decision
from ci2lab.security.decisions import DecisionAction, SecurityDecision
from ci2lab.security.engine import (
    DEFAULT_SECURITY_ENGINE,
    SecurityEngineName,
    ToolGateResult,
    enforce_ci2lab_hard_policy,
    evaluate_tool_gate,
    normalize_security_engine,
)
from ci2lab.security.opencode_permissions import OpenCodePermissionConfig
from ci2lab.security.paths import (
    PathViolationError,
    assert_within_workspace,
    is_within_workspace,
    resolve_workspace_path,
    workspace_root,
)
from ci2lab.security.policy import check_command_allowed, check_path_allowed

__all__ = [
    "DEFAULT_SECURITY_ENGINE",
    "DecisionAction",
    "OpenCodePermissionConfig",
    "PathViolationError",
    "SecurityAuditEntry",
    "SecurityDecision",
    "SecurityEngineName",
    "ToolGateResult",
    "assert_within_workspace",
    "check_command_allowed",
    "check_path_allowed",
    "clear_audit_log",
    "enforce_ci2lab_hard_policy",
    "evaluate_tool_gate",
    "get_audit_log",
    "is_within_workspace",
    "log_decision",
    "normalize_security_engine",
    "resolve_workspace_path",
    "workspace_root",
]
