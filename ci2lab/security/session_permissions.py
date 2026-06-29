"""Temporary per-session/run approvals (opencode_experimental only)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from ci2lab.security.opencode_permissions import _TOOL_TO_OPENCODE

SessionApprovalScope = Literal["allow_once", "allow_session", "deny_once"]


@dataclass(frozen=True)
class ApprovalFingerprint:
    """Cache key identifying a single approvable tool call.

    Attributes:
        engine: Canonical security engine name.
        tool_canonical: Tool name mapped to its OpenCode category.
        matched_rule: Identifier of the rule that triggered the ask.
        target_fingerprint: Normalized target (path or command).
        external_directory: True if the target lies outside the workspace.
    """

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
    """Map a tool name to its OpenCode category (e.g. ``read``/``edit``/``bash``).

    Args:
        tool_name: Concrete tool name.

    Returns:
        The OpenCode category, or ``tool_name`` itself when unmapped.
    """
    return _TOOL_TO_OPENCODE.get(tool_name, tool_name)


def _normalize_slashes(text: str) -> str:
    """Convert backslashes to forward slashes for stable comparison."""
    return text.replace("\\", "/")


def target_fingerprint(tool_name: str, args: dict[str, Any]) -> str:
    """Build a normalized fingerprint of a tool call's target.

    Args:
        tool_name: Name of the tool.
        args: Arguments passed to the tool.

    Returns:
        A normalized string identifying the command, pattern or path.
    """
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
    """Construct the cache key for a session approval lookup or grant.

    Args:
        engine: Canonical security engine name.
        tool_name: Name of the tool being approved.
        args: Arguments passed to the tool.
        matched_rule: Identifier of the rule that triggered the ask.
        external_directory: True if the target lies outside the workspace.

    Returns:
        The :class:`ApprovalFingerprint` for this tool call.
    """
    return ApprovalFingerprint(
        engine=engine,
        tool_canonical=canonical_opencode_tool(tool_name),
        matched_rule=matched_rule or "",
        target_fingerprint=target_fingerprint(tool_name, args),
        external_directory=external_directory,
    )


def bind_active_session(session_id: str | None) -> None:
    """Set the process-wide active session id used as a fallback key.

    Args:
        session_id: Session identifier to bind, or None to clear it.
    """
    global _active_session_id
    _active_session_id = session_id


def get_active_session_id() -> str | None:
    """Return the currently bound active session id, if any."""
    return _active_session_id


def resolve_session_key(
    *,
    session_id: str | None = None,
    run_id: str | None = None,
) -> str | None:
    """Resolve the effective session key from the available identifiers.

    Args:
        session_id: Explicit session id, if provided.
        run_id: Run id used when no session id is available.

    Returns:
        The first non-empty key among session id, run id and the active
        session id, or None if all are empty.
    """
    return session_id or run_id or _active_session_id


def grant_session_approval(
    session_key: str,
    fingerprint: ApprovalFingerprint,
    scope: SessionApprovalScope,
) -> None:
    """Register a temporary approval (process memory, not persisted to disk).

    Args:
        session_key: Key identifying the session that owns the approval.
        fingerprint: Fingerprint of the approved tool call.
        scope: Approval scope (``allow_once``, ``allow_session`` or
            ``deny_once``).

    Raises:
        ValueError: If ``scope`` is not a supported session scope.
    """
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
    raise ValueError(f"unsupported session scope: {scope!r}")


def lookup_session_approval(
    session_key: str | None,
    fingerprint: ApprovalFingerprint,
) -> SessionApprovalScope | None:
    """Look up a cached approval for a tool call.

    Args:
        session_key: Key identifying the session, or None.
        fingerprint: Fingerprint of the tool call to look up.

    Returns:
        The cached scope (deny takes precedence over allow), or None if no
        approval is cached.
    """
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
    """Consume a one-shot approval so it does not apply again.

    Only ``allow_once`` and ``deny_once`` scopes are consumable; other
    scopes are left untouched.

    Args:
        session_key: Key identifying the session, or None.
        fingerprint: Fingerprint of the approved tool call.
        scope: The one-shot scope to consume.
    """
    if not session_key:
        return
    key = (session_key, fingerprint)
    if scope == "allow_once":
        _allow_once.pop(key, None)
    elif scope == "deny_once":
        _deny_once.pop(key, None)


def clear_session_permissions(session_key: str | None = None) -> None:
    """Clear cached approvals.

    Args:
        session_key: If provided, clears only approvals for that session;
            if None, clears every cached approval.
    """
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
    """List approvals held in process memory (opencode_experimental only).

    Approvals are not persisted to disk and are visible only in the current
    agent/CLI process.

    Args:
        session_key: If provided, restricts the list to that session.

    Returns:
        A sorted list of row dicts describing each cached approval.
    """
    rows: list[dict[str, str]] = []
    stores: tuple[tuple[dict[tuple[str, ApprovalFingerprint], SessionApprovalScope], str], ...] = (
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
    """Count cached approvals grouped by scope.

    Args:
        session_key: If provided, restricts counting to that session.

    Returns:
        A mapping with per-scope counts plus a ``total`` key.
    """
    rows = list_session_approvals(session_key)
    counts: dict[str, int] = {"allow_session": 0, "allow_once": 0, "deny_once": 0}
    for row in rows:
        scope = row["scope"]
        if scope in counts:
            counts[scope] += 1
    counts["total"] = len(rows)
    return counts
