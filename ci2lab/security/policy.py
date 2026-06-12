"""Política unificada CI2Lab: workspace, bash guard y perfil de seguridad."""

from __future__ import annotations

from ci2lab.harness.tools.bash_safety import check_bash_blocked
from ci2lab.security.decisions import DecisionAction, SecurityDecision
from ci2lab.security.paths import PathViolationError, resolve_workspace_path


def check_path_allowed(workspace: str, requested_path: str) -> SecurityDecision:
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
    """Bloqueos duros (blocklist + rutas externas). No salta con --yes."""
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
        if blocked.startswith("Comando bloqueado:"):
            message = f"Error: {blocked}"
        else:
            message = f"Error: comando bloqueado por politica de seguridad ({blocked})."
        return SecurityDecision(
            action=DecisionAction.DENY,
            reason=blocked,
            outcome="blocked_by_workspace",
            message=message,
        )

    return SecurityDecision(action=DecisionAction.CONFIRM, reason="bash_requires_confirmation")
