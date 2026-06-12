"""Aprobaciones temporales por sesión/run (solo opencode_experimental)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from ci2lab.security.opencode_permissions import _TOOL_TO_OPENCODE

SessionApprovalScope = Literal["allow_once", "allow_session", "deny_once"]


@dataclass(frozen=True)
class ApprovalFingerprint:
    """Clave de caché para una decisión de sesión."""

    engine: str
    tool_canonical: str
    matched_rule: str
    target_fingerprint: str
    external_directory: bool


_active_session_id: str | None = None
_allow_session: dict[tuple[str, ApprovalFingerprint], SessionApprovalScope] = {}
_allow_once: dict[tuple[str, ApprovalFingerprint], SessionApprovalScope] = {}
_deny_once: dict[tuple[str, ApprovalFingerprint], SessionApprovalScope] = {}


def canonical_opencode_tool(tool_name: str) -> str:
    return _TOOL_TO_OPENCODE.get(tool_name, tool_name)


def _normalize_slashes(text: str) -> str:
    return text.replace("\\", "/")


def target_fingerprint(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name in {"bash", "shell"}:
        cmd = re.sub(r"\s+", " ", str(args.get("command", "")).strip())
        return cmd
    if tool_name in {"grep", "glob"}:
        path = _normalize_slashes(str(args.get("path", ".")))
        pattern = str(args.get("pattern", ""))
        return f"{path}|{pattern}"
    return _normalize_slashes(str(args.get("path", args.get("command", ""))))


def build_approval_fingerprint(
    *,
    engine: str,
    tool_name: str,
    args: dict[str, Any],
    matched_rule: str | None,
    external_directory: bool,
) -> ApprovalFingerprint:
    return ApprovalFingerprint(
        engine=engine,
        tool_canonical=canonical_opencode_tool(tool_name),
        matched_rule=matched_rule or "",
        target_fingerprint=target_fingerprint(tool_name, args),
        external_directory=external_directory,
    )


def bind_active_session(session_id: str | None) -> None:
    global _active_session_id
    _active_session_id = session_id


def get_active_session_id() -> str | None:
    return _active_session_id


def resolve_session_key(
    *,
    session_id: str | None = None,
    run_id: str | None = None,
) -> str | None:
    return session_id or run_id or _active_session_id


def grant_session_approval(
    session_key: str,
    fingerprint: ApprovalFingerprint,
    scope: SessionApprovalScope,
) -> None:
    """Registra aprobación temporal (memoria de proceso, no persiste en disco)."""
    key = (session_key, fingerprint)
    if scope == "allow_session":
        _allow_session[key] = scope
        _allow_once.pop(key, None)
        _deny_once.pop(key, None)
        return
    if scope == "allow_once":
        _allow_once[key] = scope
        return
    if scope == "deny_once":
        _deny_once[key] = scope
        return
    raise ValueError(f"scope de sesión no soportado: {scope!r}")


def lookup_session_approval(
    session_key: str | None,
    fingerprint: ApprovalFingerprint,
) -> SessionApprovalScope | None:
    if not session_key:
        return None
    key = (session_key, fingerprint)
    if key in _deny_once:
        return "deny_once"
    if key in _allow_session:
        return "allow_session"
    if key in _allow_once:
        return "allow_once"
    return None


def consume_session_approval(
    session_key: str | None,
    fingerprint: ApprovalFingerprint,
    scope: SessionApprovalScope,
) -> None:
    if not session_key:
        return
    key = (session_key, fingerprint)
    if scope == "allow_once":
        _allow_once.pop(key, None)
    elif scope == "deny_once":
        _deny_once.pop(key, None)


def clear_session_permissions(session_key: str | None = None) -> None:
    """Limpia aprobaciones; si session_key es None, vacía todo."""
    global _allow_session, _allow_once, _deny_once
    if session_key is None:
        _allow_session = {}
        _allow_once = {}
        _deny_once = {}
        return
    _allow_session = {k: v for k, v in _allow_session.items() if k[0] != session_key}
    _allow_once = {k: v for k, v in _allow_once.items() if k[0] != session_key}
    _deny_once = {k: v for k, v in _deny_once.items() if k[0] != session_key}


def list_session_approvals(
    session_key: str | None = None,
) -> list[dict[str, str]]:
    """
    Lista aprobaciones en memoria de proceso (solo opencode_experimental).

    No persiste en disco; visible solo en el proceso actual del agente/CLI.
    """
    rows: list[dict[str, str]] = []
    stores: tuple[tuple[dict, str], ...] = (
        (_allow_session, "allow_session"),
        (_allow_once, "allow_once"),
        (_deny_once, "deny_once"),
    )
    for store, scope in stores:
        for (sk, fp), _ in store.items():
            if session_key is not None and sk != session_key:
                continue
            rows.append(
                {
                    "session_key": sk,
                    "scope": scope,
                    "engine": fp.engine,
                    "tool": fp.tool_canonical,
                    "matched_rule": fp.matched_rule,
                    "target": fp.target_fingerprint,
                    "external_directory": str(fp.external_directory),
                }
            )
    rows.sort(key=lambda r: (r["session_key"], r["scope"], r["tool"]))
    return rows


def count_session_approvals(session_key: str | None = None) -> dict[str, int]:
    rows = list_session_approvals(session_key)
    counts: dict[str, int] = {"allow_session": 0, "allow_once": 0, "deny_once": 0}
    for row in rows:
        scope = row["scope"]
        if scope in counts:
            counts[scope] += 1
    counts["total"] = len(rows)
    return counts
