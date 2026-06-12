"""Deteccion de violaciones de politica de workspace y firmas de tool calls."""

from __future__ import annotations

from ci2lab.harness.types import ToolCall, ToolResult

POLICY_ERROR_PHRASES = (
    "ruta fuera del proyecto",
    "ruta fuera del workspace",
    "blocked by policy",
    "bloqueado por politica",
    "comando bloqueado: intenta acceder",
    "blocked_by_policy",
    "blocked_by_workspace",
    "policy_secret_file_blocked",
    "tool_blocked_by_security_profile",
)

POLICY_NUDGE_MESSAGE = (
    "A tool call was blocked because it tried to access paths outside the "
    "workspace. Do not retry the same path or use bash, copy, cp, type, cat, "
    "Get-Content, or similar commands to bypass this restriction. Reply to the "
    "user explaining that Ci2Lab only accesses files inside the workspace."
)

POLICY_REPEAT_MESSAGE = (
    "Error: bloqueado por politica de workspace. No repitas esta llamada ni "
    "uses bash para evitarla."
)


def tool_call_signature(call: ToolCall) -> str:
    if call.name == "bash":
        return f"bash::{call.arguments.get('command', '')}"
    path = call.arguments.get("path")
    if path is not None:
        return f"{call.name}::{path}"
    pattern = call.arguments.get("pattern")
    if pattern is not None:
        return f"{call.name}::{pattern}"
    return f"{call.name}::{call.arguments!r}"


def is_policy_error(result: ToolResult) -> bool:
    if result.outcome in {
        "blocked_by_policy",
        "blocked_by_workspace",
        "blocked_by_secret_policy",
        "blocked_by_security_profile",
    }:
        return True
    lower = result.content.lower()
    return any(phrase in lower for phrase in POLICY_ERROR_PHRASES)


def outcome_for_tool_output(content: str) -> str | None:
    if not content.startswith("Error:"):
        return None
    lower = content.lower()
    if "policy_secret_file_blocked" in lower:
        return "blocked_by_secret_policy"
    if any(
        phrase in lower
        for phrase in (
            "fuera del workspace",
            "comando bloqueado: intenta acceder",
        )
    ):
        return "blocked_by_workspace"
    return "failed"
