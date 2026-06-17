"""Main tool execution pipeline."""

from __future__ import annotations

from ci2lab.harness.security.policy import outcome_for_tool_output
from ci2lab.harness.security.write_permissions import WRITE_TOOLS
from ci2lab.harness.tools.bash import _format_bash_block_message
from ci2lab.harness.tools.bash_redirect import (
    shell_command_to_tool,
    tool_call_from_bash_command,
)
from ci2lab.harness.tools.bash_safety import check_bash_blocked
from ci2lab.harness.tools.dispatch import DISPATCH
from ci2lab.harness.tools.executor_parts.arguments import normalize_tool_arguments
from ci2lab.harness.tools.executor_parts.audit import (
    audit_security_decision,
    ensure_audit_persist_context,
)
from ci2lab.harness.tools.executor_parts.confirmation import resolve_tool_confirm
from ci2lab.harness.tools.executor_parts.write_tools import execute_write_tool
from ci2lab.harness.tools.filesystem import permission_summary
from ci2lab.harness.tools.paths import PathViolationError
from ci2lab.harness.tools.schemas import is_known_tool
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult
from ci2lab.security.permissions import evaluate_tool_gate
from ci2lab.settings import check_tool_allowed


# Equivalences we suggest when the skill blocks a shell tool.
_SHELL_TOOL_EQUIVALENT = {
    "bash": ("ls", "grep", "glob", "read_file"),
    "ls": ("ls",),
    "cat": ("read_file",),
    "find": ("glob",),
    "grep": ("grep",),
}


def _skill_block_hint(name: str, allowed_canon: set[str]) -> str:
    """Suggest the equivalent permitted tool so the model does not get stuck in a loop."""
    from ci2lab.harness.parsing_parts.common import map_name

    candidates = _SHELL_TOOL_EQUIVALENT.get(map_name(name), ())
    usable = [c for c in candidates if c in allowed_canon]
    if not usable:
        return " Do not retry the same tool; respond with what you already know."
    listed = ", ".join(f"`{t}`" for t in usable)
    return (
        f" Use {listed} instead of `{name}`"
        " (e.g. `ls` to list a directory, `grep`/`glob` to find files)."
    )


def execute_tool(call: ToolCall, config: AgentConfig) -> ToolResult:
    from ci2lab.harness.mcp.session import get_mcp_manager

    ensure_audit_persist_context(config)
    name = call.name
    if not is_known_tool(name):
        return ToolResult(
            tool_name=name,
            content=f"Error: unknown tool `{name}`",
            is_error=True,
            call_id=call.call_id,
        )

    # `bash read_file ...` (a native tool written as a command) is always
    # redirected to the real tool.
    if name == "bash":
        command = str(call.arguments.get("command", ""))
        redirected = tool_call_from_bash_command(command, call_id=call.call_id)
        if redirected is not None and redirected.name != "bash":
            return execute_tool(redirected, config)
        # If the skill does NOT allow `bash`, we translate simple POSIX commands
        # (`ls`, `grep`, `find`, `cat`) to the equivalent tool. Without this, a
        # restricted skill leaves the model in an infinite loop against the filter.
        if config.skill_allowed_tools is not None:
            from ci2lab.harness.parsing_parts.common import map_name as _mn

            if "bash" not in {_mn(t) for t in config.skill_allowed_tools}:
                translated = shell_command_to_tool(command, call_id=call.call_id)
                if translated is not None:
                    return execute_tool(translated, config)

    if config.skill_allowed_tools is not None and name != "skill":
        # Canonicalize names (list_files→ls, dir→ls...) on both sides to
        # tolerate skill allow-lists written with synonyms.
        from ci2lab.harness.parsing_parts.common import map_name

        canonical = map_name(name)
        allowed_canon = {map_name(t) for t in config.skill_allowed_tools}
        if canonical not in allowed_canon and name not in config.skill_allowed_tools:
            allowed_list = ", ".join(sorted(config.skill_allowed_tools))
            hint = _skill_block_hint(name, allowed_canon)
            return ToolResult(
                tool_name=name,
                content=(
                    f"Error: tool `{name}` is not allowed by the active skill. "
                    f"Allowed: {allowed_list}.{hint}"
                ),
                is_error=True,
                call_id=call.call_id,
                outcome="blocked_by_skill",
            )

    args = normalize_tool_arguments(call.arguments, tool_name=name)

    # The bash→tool redirection already happened above (before the skill filter).
    # Here we only validate that the command is not empty, to avoid erroneous
    # executions with models that emit an empty bash block.
    if name == "bash":
        if not str(args.get("command", "")).strip():
            return ToolResult(
                tool_name=name,
                content="Error: bash requires a non-empty `command`.",
                is_error=True,
                call_id=call.call_id,
                outcome="invalid_arguments",
            )

    if name.startswith("mcp__"):
        mgr = get_mcp_manager(config.cwd, connect=True)
        output = mgr.call_by_id(name, args)
        is_error = output.startswith("Error:")
        if len(output) > config.max_tool_output_chars:
            output = (
                output[: config.max_tool_output_chars]
                + f"\n... (truncated, {len(output)} characters total)"
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
        audit_security_decision(
            tool=name,
            detail=detail,
            decision="deny",
            gate=gate,
            outcome=gate.outcome or "blocked",
        )
        return ToolResult(
            tool_name=name,
            content=gate.message or "Error: blocked by security policy",
            is_error=True,
            call_id=call.call_id,
            outcome=gate.outcome,
        )

    if name in WRITE_TOOLS:
        return execute_write_tool(name, args, config, call.call_id, gate=gate)

    if gate.needs_confirm:
        audit_security_decision(
            tool=name, detail=detail, decision="ask", gate=gate, outcome="pending"
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
                confirm_extra=confirm_extra or None,
            )
            return ToolResult(
                tool_name=name,
                content=deny_msg or "Denegado",
                is_error=True,
                call_id=call.call_id,
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
            confirm_extra=confirm_extra or None,
        )
    else:
        audit_security_decision(
            tool=name, detail=detail, decision="allow", gate=gate, outcome="executed"
        )

    if name == "bash":
        blocked = check_bash_blocked(
            str(args.get("command", "")),
            cwd=config.cwd,
        )
        if blocked:
            audit_security_decision(
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
        audit_security_decision(
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
        audit_security_decision(
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

