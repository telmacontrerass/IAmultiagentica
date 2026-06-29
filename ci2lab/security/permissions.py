"""Permissions facade: dispatches to the active security engine."""

from __future__ import annotations

from typing import Any

from ci2lab.harness.types import AgentConfig
from ci2lab.security.engine import ToolGateResult, evaluate_tool_gate

__all__ = ["ToolGateResult", "evaluate_tool_gate", "should_confirm_tool"]


def should_confirm_tool(tool_name: str, gate: ToolGateResult) -> bool:
    """Return whether a gated tool still requires user confirmation.

    Args:
        tool_name: Name of the tool being evaluated (currently unused).
        gate: Result produced by :func:`evaluate_tool_gate`.

    Returns:
        True if the tool may proceed but needs explicit confirmation.
    """
    return gate.proceed and gate.needs_confirm


def permission_summary_for_gate(tool_name: str, args: dict[str, Any]) -> str:
    """Build a short, human-readable summary of a tool call for prompts.

    Args:
        tool_name: Name of the tool being summarized.
        args: Arguments passed to the tool.

    Returns:
        A concise, truncated description of the tool's target.
    """
    if tool_name == "bash":
        return str(args.get("command", ""))[:120]
    if "path" in args:
        return str(args["path"])
    if "pattern" in args:
        return str(args["pattern"])
    return str(args)[:120]
