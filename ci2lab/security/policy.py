"""Unified CI2Lab policy: workspace, bash guard and security profile."""

from __future__ import annotations

from ci2lab.harness.tools.bash_safety import check_bash_blocked
from ci2lab.security.decisions import DecisionAction, SecurityDecision
from ci2lab.security.paths import PathViolationError, resolve_workspace_path


def check_path_allowed(workspace: str, requested_path: str) -> SecurityDecision:
    """Apply hard path policy: workspace confinement plus secret-file blocks.

    Args:
        workspace: Path to the workspace root.
        requested_path: Path the tool wants to access.

    Returns:
        A :class:`SecurityDecision` that allows the path or denies it for
        being outside the workspace or matching the secret-file policy.
    """
    from ci2lab.harness.tools.secret_files import (
        is_sensitive_path,
        secret_file_block_message,
    )

    try:
        resolved = resolve_workspace_path(workspace, requested_path)
    except PathViolationError as exc:
        return SecurityDecision(
            action=DecisionAction.DENY,
            reason="outside_workspace",
            outcome="blocked_by_workspace",
            message=str(exc),
        )
    if is_sensitive_path(resolved, workspace=workspace):
        return SecurityDecision(
            action=DecisionAction.DENY,
            reason="secret_file",
            outcome="blocked_by_secret_policy",
            message=secret_file_block_message(),
        )
    return SecurityDecision(action=DecisionAction.ALLOW, reason="within_workspace")


def check_command_allowed(
    command: str,
    workspace: str,
    *,
    security_profile: str = "standard",
) -> SecurityDecision:
    """Apply hard bash policy: security profile plus the command blocklist.

    These are hard blocks (blocklist and security profile) that cannot be
    bypassed with ``--yes`` / auto-confirm.

    Args:
        command: The shell command to evaluate.
        workspace: Path to the workspace root (used as the command cwd).
        security_profile: Name of the active security profile.

    Returns:
        A :class:`SecurityDecision` that denies blocked commands or requires
        confirmation for any other command.
    """
    from ci2lab.harness.security_profiles import (
        is_tool_blocked_by_profile,
        profile_block_message,
    )

    if is_tool_blocked_by_profile(security_profile, "bash"):
        return SecurityDecision(
            action=DecisionAction.DENY,
            reason="security_profile",
            outcome="blocked_by_security_profile",
            message=profile_block_message("bash", security_profile),
        )

    blocked = check_bash_blocked(command, cwd=workspace)
    if blocked:
        if blocked.startswith("Blocked command:"):
            message = f"Error: {blocked}"
        else:
            # The eval matcher in ci2lab/evals/task.py and the task fixture
            # evals/tasks/004_block_dangerous_bash.json detect blocked dangerous
            # commands by the substring "blocked by security policy".
            message = f"Error: command blocked by security policy ({blocked})."
        return SecurityDecision(
            action=DecisionAction.DENY,
            reason=blocked,
            outcome="blocked_by_workspace",
            message=message,
        )

    return SecurityDecision(action=DecisionAction.CONFIRM, reason="bash_requires_confirmation")
