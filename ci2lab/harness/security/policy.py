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
    """Build a stable signature string identifying a tool call.

    Used to detect repeated calls (e.g. a model retrying a blocked path). Prefers
    the bash command, then a ``path`` or ``pattern`` argument, falling back to a
    repr of all arguments.

    Args:
        call: The tool call to summarize.

    Returns:
        A ``<name>::<discriminator>`` signature string.
    """
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
    """Return whether a tool result represents a workspace-policy violation.

    Checks the structured ``outcome`` field first, then scans the result content
    for any of :data:`POLICY_ERROR_PHRASES`.

    Args:
        result: The tool result to classify.

    Returns:
        ``True`` if the result was blocked by policy.
    """
    if result.outcome in {
        "blocked_by_policy",
        "blocked_by_workspace",
        "blocked_by_secret_policy",
    }:
        return True
    lower = result.content.lower()
    return any(phrase in lower for phrase in POLICY_ERROR_PHRASES)


def outcome_for_tool_output(content: str) -> str | None:
    """Classify raw tool output text into a structured outcome label.

    Only error output (text starting with ``Error:``) is classified; a blocked
    secret file or out-of-workspace access maps to its specific outcome, other
    errors to ``"failed"``.

    Args:
        content: The tool's raw output text.

    Returns:
        ``"blocked_by_secret_policy"``, ``"blocked_by_workspace"``,
        ``"command_failed"`` or ``"failed"`` for error output, or ``None`` when
        the output is not an error.
    """
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
    if lower.startswith("error: command exited with code"):
        # A shell command that ran and returned non-zero. Kept distinct from
        # "failed" so the loop treats it as an observed result (e.g. a red
        # test run) rather than an infrastructure failure.
        return "command_failed"
    return "failed"
