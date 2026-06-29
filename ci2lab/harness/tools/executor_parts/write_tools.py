"""Execution path for write/edit tools with previews and confirmations."""

from __future__ import annotations

from typing import Any

from ci2lab.harness.security.policy import outcome_for_tool_output
from ci2lab.harness.security.write_permissions import check_write_permission
from ci2lab.harness.tools.dispatch import DISPATCH
from ci2lab.harness.tools.executor_parts.audit import audit_security_decision
from ci2lab.harness.tools.executor_parts.confirmation import resolve_tool_confirm
from ci2lab.harness.tools.paths import PathViolationError
from ci2lab.harness.tools.write_preview import (
    preview_apply_patch,
    preview_docx_to_pdf,
    preview_edit_file,
    preview_pdf_to_docx,
    preview_write_file,
)
from ci2lab.harness.types import AgentConfig, ToolResult
from ci2lab.security.engine import ToolGateResult, enforce_ci2lab_hard_policy


def execute_write_tool(
    name: str,
    args: dict[str, Any],
    config: AgentConfig,
    call_id: str | None,
    *,
    gate: ToolGateResult | None = None,
) -> ToolResult:
    """Execute a write/edit tool with preview, validation and confirmation.

    Builds a diff/content preview for the requested write tool, validates it,
    optionally prompts for confirmation (and displays the diff when enabled),
    and finally dispatches the real tool. Path violations and validation
    failures are converted into error :class:`ToolResult` objects rather than
    raised.

    Args:
        name: Canonical write-tool name (e.g. ``write_file``, ``edit_file``,
            ``apply_patch``, ``docx_to_pdf``).
        args: Normalized tool arguments for the write operation.
        config: Active agent configuration controlling write enablement,
            security engine and preview behavior.
        call_id: Identifier of the originating tool call, echoed back on the
            result; may be ``None``.
        gate: Gate result from the security evaluation. When ``None``,
            confirmation is assumed to be required.

    Returns:
        A :class:`ToolResult` describing success, denial or error, with an
        ``outcome`` label suitable for auditing.
    """
    if not config.write_tools_enabled:
        return ToolResult(
            tool_name=name,
            content=(f"Error: `{name}` disabled by configuration (write_tools_enabled=false)."),
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

            preview = preview_write_docx(config.cwd, args["path"], args["content"])
        elif name == "apply_patch":
            preview = preview_apply_patch(config.cwd, args["patch"])
        elif name == "fill_docx_template":
            from ci2lab.harness.tools.docx_writer import preview_fill_docx

            preview = preview_fill_docx(config.cwd, args)
        elif name == "docx_to_pdf":
            preview = preview_docx_to_pdf(config.cwd, args["source"], args["output"])
        elif name == "pdf_to_docx":
            preview = preview_pdf_to_docx(config.cwd, args["source"], args["output"])
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
    except Exception as exc:
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call_id,
            outcome="failed",
        )

    if not preview.is_valid:
        err_msg = preview.validation_error or "Validation error"
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
            audit_security_decision(
                tool=name,
                detail=detail,
                decision="ask",
                gate=gate,
                outcome="pending",
            )
            allowed, deny_msg, reason, confirm_extra = resolve_tool_confirm(
                name, args, detail, gate, config
            )
            if not allowed:
                audit_security_decision(
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
            audit_security_decision(
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
    except Exception as exc:
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
