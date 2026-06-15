"""Workspace path access checks for filesystem tools."""

from __future__ import annotations

from pathlib import Path

from ci2lab.harness.tools.paths import PathViolationError, resolve_path
from ci2lab.harness.tools.secret_files import is_sensitive_path


def resolve_or_error(raw: str, cwd: str) -> tuple[Path | None, str | None]:
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
    from ci2lab.security.engine import enforce_ci2lab_hard_policy

    if enforce_ci2lab_hard_policy(security_engine):
        return resolve_or_error(raw, cwd)
    try:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        return candidate.resolve(), None
    except OSError as exc:
        return None, f"Error: ruta invalida: {exc}"


def check_sensitive(
    resolved: Path,
    cwd: str,
    *,
    security_engine: str = "ci2lab",
) -> bool:
    from ci2lab.security.engine import enforce_ci2lab_hard_policy

    if not enforce_ci2lab_hard_policy(security_engine):
        return False
    return is_sensitive_path(resolved, workspace=cwd)

