"""Fachada de permisos: despacha al motor de seguridad activo."""

from __future__ import annotations

from typing import Any

from ci2lab.harness.types import AgentConfig
from ci2lab.security.engine import ToolGateResult, evaluate_tool_gate

__all__ = ["ToolGateResult", "evaluate_tool_gate", "should_confirm_tool"]


def should_confirm_tool(tool_name: str, gate: ToolGateResult) -> bool:
    return gate.proceed and gate.needs_confirm


def permission_summary_for_gate(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "bash":
        return str(args.get("command", ""))[:120]
    if "path" in args:
        return str(args["path"])
    if "pattern" in args:
        return str(args["pattern"])
    return str(args)[:120]
