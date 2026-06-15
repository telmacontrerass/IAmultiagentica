"""Execute normalized tool calls."""

from __future__ import annotations

import json
from typing import Any

from ci2lab.harness.security.permissions import check_permission
from ci2lab.harness.security.policy import outcome_for_tool_output
from ci2lab.harness.security.write_permissions import WRITE_TOOLS, check_write_permission
from ci2lab.harness.tools.arg_normalize import normalize_args_for_tool
from ci2lab.harness.tools.bash import _format_bash_block_message
from ci2lab.harness.tools.bash_redirect import tool_call_from_bash_command
from ci2lab.harness.tools.bash_safety import check_bash_blocked
from ci2lab.harness.tools.dispatch import DISPATCH
from ci2lab.harness.tools.filesystem import permission_summary
from ci2lab.harness.tools.paths import PathViolationError
from ci2lab.harness.tools.schemas import is_known_tool
from ci2lab.harness.tools.write_preview import (
    preview_apply_patch,
    preview_edit_file,
    preview_write_file,
)
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult
from ci2lab.security.audit import (
    AuditPersistContext,
    get_audit_persist_context,
    log_decision,
    set_audit_persist_context,
)
from ci2lab.security.engine import ToolGateResult, enforce_ci2lab_hard_policy
from ci2lab.security.permissions import evaluate_tool_gate
from ci2lab.settings import check_tool_allowed


def normalize_tool_arguments(
    args: dict[str, Any],
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    cleaned = {k: v for k, v in args.items() if v is not None}
    if tool_name:
        return normalize_args_for_tool(tool_name, cleaned)
    return cleaned


def parse_arguments(
    raw: str | dict[str, Any],
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    if isinstance(raw, dict):
        return normalize_tool_arguments(raw, tool_name=tool_name)
    if not raw or not str(raw).strip():
        return {}
    try:
        return normalize_tool_arguments(json.loads(raw), tool_name=tool_name)
    except json.JSONDecodeError:
        return {"command": str(raw)} if raw else {}


def _ensure_audit_persist_context(config: AgentConfig) -> None:
    if get_audit_persist_context() is not None:
        return
    set_audit_persist_context(
        AuditPersistContext(
            workspace=config.cwd,
            runs_dir=config.runs_dir,
            security_engine=config.security_engine,
        )
    )


def _audit_security_decision(
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


def _resolve_tool_confirm(
    name: str,
    args: dict[str, Any],
    detail: str,
    gate: ToolGateResult,
    config: AgentConfig,
) -> tuple[bool, str | None, str, dict[str, Any]]:
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


def _execute_write_tool(
    name: str,
    args: dict[str, Any],
    config: AgentConfig,
    call_id: str | None,
    *,
    gate: ToolGateResult | None = None,
) -> ToolResult:
    if not config.write_tools_enabled:
        return ToolResult(
            tool_name=name,
            content=(
                f"Error: `{name}` deshabilitado por configuración "
                "(write_tools_enabled=false)."
            ),
            is_error=True,
            call_id=call_id,
            outcome="blocked_by_config",
        )

    enforce_hard = enforce_ci2lab_hard_policy(config.security_engine)
    try:
        if name == "write_file":
            preview = preview_write_file(
                config.cwd,
                args["path"],
                args["content"],
                enforce_hard_policy=enforce_hard,
            )
        elif name == "write_docx":
            from ci2lab.harness.tools.write_preview import preview_write_docx

            preview = preview_write_docx(
                config.cwd, args["path"], args["content"]
            )
        elif name == "apply_patch":
            preview = preview_apply_patch(config.cwd, args["patch"])
        elif name == "fill_docx_template":
            from ci2lab.harness.tools.docx_writer import preview_fill_docx

            preview = preview_fill_docx(config.cwd, args)
        else:
            preview = preview_edit_file(
                config.cwd,
                args["path"],
                args["old_string"],
                args["new_string"],
                args.get("replace_all", False),
                enforce_hard_policy=enforce_hard,
            )
    except PathViolationError as exc:
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call_id,
            outcome="blocked_by_workspace",
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call_id,
            outcome="failed",
        )

    if not preview.is_valid:
        err_msg = preview.validation_error or "Error de validación"
        return ToolResult(
            tool_name=name,
            content=err_msg,
            is_error=True,
            call_id=call_id,
            outcome=outcome_for_tool_output(err_msg) or "failed",
        )

    needs_confirm = gate.needs_confirm if gate is not None else True
    if needs_confirm:
        from ci2lab.security.approval_prompt import uses_modern_permission_prompt

        detail = preview.path
        if uses_modern_permission_prompt(config.security_engine) and gate is not None:
            if config.require_diff_preview:
                from rich.panel import Panel

                from ci2lab.console import console

                console.print(
                    Panel(
                        preview.format_for_display(),
                        title=f"Preview: {name}",
                        border_style="yellow",
                    )
                )
            _audit_security_decision(
                tool=name,
                detail=detail,
                decision="ask",
                gate=gate,
                outcome="pending",
            )
            allowed, deny_msg, reason, confirm_extra = _resolve_tool_confirm(
                name, args, detail, gate, config
            )
            if not allowed:
                _audit_security_decision(
                    tool=name,
                    detail=detail,
                    decision="deny",
                    gate=gate,
                    reason=reason,
                    confirmed=False,
                    outcome="denied",
                    confirm_extra=confirm_extra,
                )
                return ToolResult(
                    tool_name=name,
                    content=deny_msg or "Denegado",
                    is_error=True,
                    call_id=call_id,
                    outcome="denied",
                )
            _audit_security_decision(
                tool=name,
                detail=detail,
                decision="allow",
                gate=gate,
                reason=reason,
                confirmed=True,
                outcome="executed",
                confirm_extra=confirm_extra,
            )
        else:
            allowed, deny_msg = check_write_permission(name, preview, config)
            if not allowed:
                return ToolResult(
                    tool_name=name,
                    content=deny_msg or "Denegado",
                    is_error=True,
                    call_id=call_id,
                    outcome="denied",
                )

    try:
        output = DISPATCH[name](config, args)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call_id,
            outcome="failed",
        )

    is_error = output.startswith("Error:")
    return ToolResult(
        tool_name=name,
        content=output,
        is_error=is_error,
        call_id=call_id,
        outcome="failed" if is_error else "approved",
    )


def execute_tool(call: ToolCall, config: AgentConfig) -> ToolResult:
    from ci2lab.harness.mcp.session import get_mcp_manager

    _ensure_audit_persist_context(config)
    name = call.name
    if not is_known_tool(name):
        return ToolResult(
            tool_name=name,
            content=f"Error: herramienta desconocida `{name}`",
            is_error=True,
            call_id=call.call_id,
        )

    if (
        config.skill_allowed_tools is not None
        and name not in config.skill_allowed_tools
        and name != "skill"
    ):
        return ToolResult(
            tool_name=name,
            content=(
                f"Error: tool `{name}` is not allowed by the active skill. "
                f"Allowed: {', '.join(sorted(config.skill_allowed_tools))}"
            ),
            is_error=True,
            call_id=call.call_id,
        )

    args = normalize_tool_arguments(call.arguments, tool_name=name)

    if name == "bash":
        redirected = tool_call_from_bash_command(
            str(args.get("command", "")), call_id=call.call_id
        )
        if redirected is not None:
            return execute_tool(redirected, config)

    if name.startswith("mcp__"):
        mgr = get_mcp_manager(config.cwd, connect=True)
        output = mgr.call_by_id(name, args)
        is_error = output.startswith("Error:")
        if len(output) > config.max_tool_output_chars:
            output = (
                output[: config.max_tool_output_chars]
                + f"\n... (truncado, {len(output)} caracteres totales)"
            )
        return ToolResult(
            tool_name=name,
            content=output,
            is_error=is_error,
            call_id=call.call_id,
            outcome=outcome_for_tool_output(output) if is_error else None,
        )

    if config.tool_settings is not None:
        settings_allowed, settings_reason = check_tool_allowed(
            config.tool_settings, name, args
        )
        if not settings_allowed:
            return ToolResult(
                tool_name=name,
                content=f"Error: {settings_reason}",
                is_error=True,
                call_id=call.call_id,
                outcome="blocked_by_settings",
            )

    detail = permission_summary(name, args) or str(args)[:120]
    gate = evaluate_tool_gate(name, args, config)
    if gate.blocked:
        _audit_security_decision(
            tool=name,
            detail=detail,
            decision="deny",
            gate=gate,
            outcome=gate.outcome or "blocked",
        )
        return ToolResult(
            tool_name=name,
            content=gate.message or "Error: bloqueado por politica de seguridad",
            is_error=True,
            call_id=call.call_id,
            outcome=gate.outcome,
        )

    if name in WRITE_TOOLS:
        return _execute_write_tool(name, args, config, call.call_id, gate=gate)

    if gate.needs_confirm:
        _audit_security_decision(
            tool=name, detail=detail, decision="ask", gate=gate, outcome="pending"
        )
        allowed, deny_msg, reason, confirm_extra = _resolve_tool_confirm(
            name, args, detail, gate, config
        )
        if not allowed:
            _audit_security_decision(
                tool=name,
                detail=detail,
                decision="deny",
                gate=gate,
                reason=reason,
                confirmed=False,
                outcome="denied",
                confirm_extra=confirm_extra or None,
            )
            return ToolResult(
                tool_name=name,
                content=deny_msg or "Denegado",
                is_error=True,
                call_id=call.call_id,
                outcome="denied",
            )
        _audit_security_decision(
            tool=name,
            detail=detail,
            decision="allow",
            gate=gate,
            reason=reason,
            confirmed=True,
            outcome="executed",
            confirm_extra=confirm_extra or None,
        )
    else:
        _audit_security_decision(
            tool=name, detail=detail, decision="allow", gate=gate, outcome="executed"
        )

    if name == "bash":
        blocked = check_bash_blocked(
            str(args.get("command", "")),
            cwd=config.cwd,
        )
        if blocked:
            _audit_security_decision(
                tool=name,
                detail=detail,
                decision="deny",
                gate=gate,
                reason="blocked_by_workspace",
                outcome="blocked_by_workspace",
            )
            return ToolResult(
                tool_name=name,
                content=_format_bash_block_message(blocked),
                is_error=True,
                call_id=call.call_id,
                outcome="blocked_by_workspace",
            )

    try:
        output = DISPATCH[name](config, args)
    except PathViolationError as exc:
        _audit_security_decision(
            tool=name,
            detail=detail,
            decision="deny",
            gate=gate,
            reason="outside_workspace",
            outcome="blocked_by_workspace",
        )
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call.call_id,
            outcome="blocked_by_workspace",
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call.call_id,
        )

    if len(output) > config.max_tool_output_chars:
        output = (
            output[: config.max_tool_output_chars]
            + f"\n... (truncado, {len(output)} caracteres totales)"
        )
    is_error = output.startswith("Error:")
    if is_error:
        _audit_security_decision(
            tool=name,
            detail=detail,
            decision="deny",
            gate=gate,
            reason=outcome_for_tool_output(output) or "tool_error",
            outcome="error",
        )
    return ToolResult(
        tool_name=name,
        content=output,
        is_error=is_error,
        call_id=call.call_id,
        outcome=outcome_for_tool_output(output) if is_error else None,
    )
