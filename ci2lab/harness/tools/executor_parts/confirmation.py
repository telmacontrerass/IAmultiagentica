"""Permission confirmation helpers for tool execution."""

from __future__ import annotations

from typing import Any

from ci2lab.harness.security.permissions import check_permission
from ci2lab.harness.types import AgentConfig
from ci2lab.security.engine import ToolGateResult


def resolve_tool_confirm(
    name: str,
    args: dict[str, Any],
    detail: str,
    gate: ToolGateResult,
    config: AgentConfig,
) -> tuple[bool, str | None, str, dict[str, Any]]:
    """Resolve a confirmation prompt for a tool that requires user approval.

    Dispatches to the modern approval-prompt flow when the active security
    engine supports it, otherwise falls back to the legacy permission check.

    Args:
        name: Canonical tool name being confirmed.
        args: Normalized tool arguments.
        detail: Human-readable summary of the pending action.
        gate: Gate result that triggered the confirmation.
        config: Active agent configuration (security engine, auto-confirm,
            confirm callback).

    Returns:
        A 4-tuple ``(allowed, deny_message, reason, extra)`` where ``allowed``
        indicates whether to proceed, ``deny_message`` is the message to return
        when denied (``None`` when allowed), ``reason`` is the audit reason code
        and ``extra`` carries additional approval metadata for the audit record.
    """
    from ci2lab.security.approval_prompt import (
        confirm_opencode_ask,
        uses_modern_permission_prompt,
    )

    if uses_modern_permission_prompt(config.security_engine):
        result = confirm_opencode_ask(
            config=config,
            tool_name=name,
            args=args,
            gate=gate,
            detail=detail,
        )
        extra = {
            "approval_choice": result.choice.value if result.choice else None,
            "session_scope_granted": result.session_scope_granted,
        }
        if result.proceed:
            return True, None, result.reason, extra
        return False, result.message, result.reason, extra

    allowed, deny_msg = check_permission(
        name,
        detail,
        auto_confirm=config.auto_confirm,
        confirm_callback=config.confirm_callback,
    )
    if allowed:
        reason = "confirmed" if config.auto_confirm else "user_confirmed"
        return True, None, reason, {}
    return False, deny_msg, "user_denied", {}
