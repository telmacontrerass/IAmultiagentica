"""Shell command execution with a timeout."""

from __future__ import annotations

import subprocess

from ci2lab.security.decisions import DecisionAction
from ci2lab.security.engine import enforce_ci2lab_hard_policy
from ci2lab.security.policy import check_command_allowed


def _format_bash_block_message(blocked: str) -> str:
    """Render a security-block reason as a user-facing error message.

    Args:
        blocked: Either a pre-formatted ``"Blocked command: ..."`` reason or a
            short rule description.

    Returns:
        The error string to surface to the model.
    """
    if blocked.startswith("Blocked command:"):
        return f"Error: {blocked}"
    return f"Error: command blocked by security policy ({blocked})."


def run_bash(
    cwd: str,
    command: str,
    timeout_seconds: int = 60,
    *,
    security_profile: str = "standard",
    security_engine: str = "ci2lab",
) -> str:
    """Run a shell command in ``cwd`` with a timeout and capture its output.

    The command is first checked against the active security policy; if denied,
    the policy's message is returned instead of executing anything. Output combines
    stdout, stderr (prefixed with ``[stderr]``) and a non-zero exit-code marker.

    Args:
        cwd: Working directory in which to run the command.
        command: The shell command line to execute.
        timeout_seconds: Maximum wall-clock time before the command is aborted.
        security_profile: Security profile name passed to the policy check.
        security_engine: Identifier of the security engine to enforce.

    Returns:
        The combined command output, a policy-block message, or an error string
        describing a timeout or OS-level failure.
    """
    if not command.strip():
        return "Error: bash requires a non-empty `command`."
    if enforce_ci2lab_hard_policy(security_engine):
        decision = check_command_allowed(command, cwd, security_profile=security_profile)
        if decision.action is DecisionAction.DENY:
            return decision.message or _format_bash_block_message(decision.reason)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command exceeded the {timeout_seconds}s timeout"
    except OSError as exc:
        return f"Error running command: {exc}"

    parts: list[str] = []
    if proc.stdout:
        parts.append(proc.stdout.rstrip())
    if proc.stderr:
        parts.append(f"[stderr]\n{proc.stderr.rstrip()}")
    if proc.returncode != 0:
        parts.append(f"[exit code {proc.returncode}]")
    return "\n".join(parts) if parts else f"(no output, exit {proc.returncode})"
