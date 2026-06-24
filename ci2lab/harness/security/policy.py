"""Workspace-policy violation detection and tool-call signatures.

The phrase lists below are matched against tool *output* so detection keeps
working regardless of how a tool phrases its block message.
"""

from __future__ import annotations

from ci2lab.harness.types import ToolCall, ToolResult

POLICY_ERROR_PHRASES = (
    "path outside the project",
    "path outside the workspace",
    "blocked by policy",
    "blocked command: tries to access",
    "blocked_by_policy",
    "blocked_by_workspace",
    "policy_secret_file_blocked",
)

POLICY_NUDGE_MESSAGE = (
    "A tool call was blocked because it tried to access paths outside the "
    "workspace. Do not retry the same path or use bash, copy, cp, type, cat, "
    "Get-Content, or similar commands to bypass this restriction. Reply to the "
    "user explaining that Ci2Lab only accesses files inside the workspace."
)

POLICY_REPEAT_MESSAGE = (
    "Error: blocked by workspace policy. Do not repeat this call and do not use "
    "bash to work around it."
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
            "outside the workspace",
            "blocked command: tries to access",
        )
    ):
        return "blocked_by_workspace"
    return "failed"
