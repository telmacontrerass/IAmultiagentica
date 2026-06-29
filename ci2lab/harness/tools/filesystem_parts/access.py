"""Workspace path access checks for filesystem tools."""

from __future__ import annotations

from pathlib import Path

from ci2lab.harness.tools.paths import PathViolationError, resolve_path
from ci2lab.harness.tools.secret_files import is_sensitive_path


def resolve_or_error(raw: str, cwd: str) -> tuple[Path | None, str | None]:
    """Resolve ``raw`` against ``cwd`` enforcing the workspace path policy.

    Args:
        raw: The user-supplied path, absolute or relative.
        cwd: The workspace root used to anchor relative paths and bound access.

    Returns:
        A ``(resolved_path, error)`` pair. On success the path is set and the
        error is ``None``; on a policy violation the path is ``None`` and the
        error is a human-readable ``"Error: ..."`` message.
    """
    try:
        return resolve_path(raw, cwd), None
    except PathViolationError as exc:
        return None, f"Error: {exc}"


def resolve_for_access(
    raw: str,
    cwd: str,
    *,
    security_engine: str = "ci2lab",
) -> tuple[Path | None, str | None]:
    """Resolve a path for read/access, honouring the active security engine.

    When the hard ci2lab policy is active, this defers to
    :func:`resolve_or_error`. Otherwise it performs a permissive resolution
    that expands ``~`` and anchors relative paths to ``cwd`` without enforcing
    workspace containment.

    Args:
        raw: The user-supplied path, absolute or relative.
        cwd: The workspace root used to anchor relative paths.
        security_engine: Identifier of the security engine to consult.

    Returns:
        A ``(resolved_path, error)`` pair, mirroring :func:`resolve_or_error`.
    """
    from ci2lab.security.engine import enforce_ci2lab_hard_policy

    if enforce_ci2lab_hard_policy(security_engine):
        return resolve_or_error(raw, cwd)
    try:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        return candidate.resolve(), None
    except OSError as exc:
        return None, f"Error: invalid path: {exc}"


def check_sensitive(
    resolved: Path,
    cwd: str,
    *,
    security_engine: str = "ci2lab",
) -> bool:
    """Report whether ``resolved`` is sensitive under the active security engine.

    Args:
        resolved: The already-resolved path to evaluate.
        cwd: The workspace root, used to scope the sensitivity check.
        security_engine: Identifier of the security engine to consult.

    Returns:
        ``True`` if the hard ci2lab policy is active and the path looks
        sensitive; ``False`` otherwise (including when the policy is inactive).
    """
    from ci2lab.security.engine import enforce_ci2lab_hard_policy

    if not enforce_ci2lab_hard_policy(security_engine):
        return False
    return is_sensitive_path(resolved, workspace=cwd)
