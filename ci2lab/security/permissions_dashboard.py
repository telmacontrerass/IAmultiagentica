"""Reading and summary of the permissions audit (CLI dashboard like /permissions)."""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ci2lab.security.audit import resolve_audit_path_within_workspace
from ci2lab.security.engine import CI2LAB_GUARD_EXTERNAL_ALLOW_IGNORED, uses_permission_layer
from ci2lab.security.gate_check import build_tool_args, evaluate_security_gate
from ci2lab.security.session_permissions import (
    ApprovalFingerprint,
    build_approval_fingerprint,
)

_TABLE_COLUMNS = (
    "event_id",
    "timestamp",
    "tool",
    "target",
    "decision",
    "reason",
    "matched_rule",
    "outcome",
)

_EXTERNAL_WARNING = "UNSAFE: external_directory=true - access outside the workspace"

_DENIED_OUTCOMES = frozenset(
    {
        "blocked",
        "blocked_by_workspace",
        "blocked_by_secret_policy",
        "blocked_by_security_profile",
        "blocked_by_config",
        "denied",
        "error",
    }
)


def load_audit_events(path: str | Path) -> list[dict[str, Any]]:
    """Load JSONL events. Invalid lines are skipped with an implicit notice."""
    audit_path = Path(path).expanduser().resolve()
    if not audit_path.is_file():
        raise FileNotFoundError(f"Audit file does not exist: {audit_path}")

    events: list[dict[str, Any]] = []
    for line_no, raw in enumerate(audit_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {audit_path}:{line_no}: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"Line {line_no} in {audit_path}: must be a JSON object.")
        events.append(_normalize_event(record))
    return events


def compute_event_id(record: dict[str, Any]) -> str:
    """Stable ID derived from event fields (12 hex chars)."""
    target = str(record.get("target", record.get("detail", "")))
    parts = [
        str(record.get("timestamp", "")),
        str(record.get("run_id") or ""),
        str(record.get("tool", "")),
        target,
        str(record.get("decision", "")),
        str(record.get("reason", "")),
        str(record.get("matched_rule") or ""),
    ]
    digest = hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


def _normalize_event(record: dict[str, Any]) -> dict[str, Any]:
    """Unify legacy and nested fields."""
    event = dict(record)
    event.setdefault("target", record.get("detail", ""))
    if "approval_choice" not in event:
        extra = record.get("extra")
        if isinstance(extra, dict) and "approval_choice" in extra:
            event["approval_choice"] = extra["approval_choice"]
    event["event_id"] = compute_event_id(event)
    return event


def find_event_by_id(
    events: list[dict[str, Any]],
    event_id: str,
) -> dict[str, Any] | None:
    """Return the event whose id matches ``event_id``, or None.

    Args:
        events: Normalized audit events to search.
        event_id: Event id to look up (case-insensitive).

    Returns:
        The matching event dict, or None if not found.
    """
    needle = event_id.strip().lower()
    for ev in events:
        if str(ev.get("event_id", "")).lower() == needle:
            return ev
    return None


def parse_target_to_args(tool: str, target: str) -> dict[str, Any]:
    """Reconstruct minimal tool args from an audit event's tool and target.

    Args:
        tool: Tool name from the audit event.
        target: Target string, which may be a literal dict or a plain value.

    Returns:
        An arguments dict suitable for gate evaluation.
    """
    text = target.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return dict(parsed)
        except (ValueError, SyntaxError):
            pass
    return build_tool_args(tool, text)


def _gate_target_for_eval(tool: str, args: dict[str, Any]) -> str:
    """Pick the single target string a dry gate evaluation needs for ``tool``."""
    if tool in {"bash", "shell"}:
        return str(args.get("command", ""))
    if tool in {"grep", "glob"}:
        return str(args.get("pattern", args.get("path", "")))
    return str(args.get("path", ""))


def approval_from_audit_event(
    event: dict[str, Any],
) -> tuple[ApprovalFingerprint, list[str]]:
    """
    Build a fingerprint for approve-session.

    Raises ValueError if the event is not eligible.
    """
    warnings: list[str] = []
    engine = str(event.get("security_engine", ""))
    if engine == "ci2lab":
        raise ValueError("approve-session does not apply to ci2lab; use permission-layer engines.")
    if not uses_permission_layer(engine):
        raise ValueError(f"Unsupported engine for approve-session: {engine!r}")

    decision = str(event.get("decision", "")).lower()
    approval_choice = event.get("approval_choice")
    if decision == "deny":
        matched = str(event.get("matched_rule") or "")
        if matched.startswith("hard:"):
            raise ValueError(
                "Cannot approve: hard block (workspace/secret/bash/profile). "
                "Changing the permission config will not bypass it."
            )
        raise ValueError("Cannot approve: the event was denied by a permission rule.")
    if decision != "ask" and approval_choice != "deny_once":
        raise ValueError(
            "approve-session only applies to events with decision=ask or approval_choice=deny_once."
        )

    tool = event.get("tool")
    target = event.get("target")
    if not tool or target is None or str(target).strip() == "":
        raise ValueError("Missing tool/target fields to build the fingerprint.")

    external = bool(event.get("external_directory"))
    if external:
        warnings.append(_EXTERNAL_WARNING)

    args = parse_target_to_args(str(tool), str(target))
    fingerprint = build_approval_fingerprint(
        engine=engine,
        tool_name=str(tool),
        args=args,
        matched_rule=str(event.get("matched_rule") or ""),
        external_directory=external,
    )
    return fingerprint, warnings


def _is_outside_workspace_event(event: dict[str, Any]) -> bool:
    """Return whether an audit event represents an outside-workspace block."""
    reason = str(event.get("reason", ""))
    matched = str(event.get("matched_rule") or "")
    outcome = str(event.get("outcome") or "")
    return (
        reason == "outside_workspace"
        or matched == "hard:outside_workspace"
        or (
            outcome == "blocked_by_workspace"
            and bool(event.get("hard_guards_enabled"))
            and "secret" not in reason
        )
    )


def _is_secret_event(event: dict[str, Any]) -> bool:
    """Return whether an audit event represents a secret-file block."""
    matched = str(event.get("matched_rule") or "")
    reason = str(event.get("reason", ""))
    outcome = str(event.get("outcome") or "")
    target = str(event.get("target", "")).lower()
    return (
        matched == "hard:secret_file"
        or reason == "secret_file"
        or outcome == "blocked_by_secret_policy"
        or ".env" in target
    )


def build_retry_plan(
    event: dict[str, Any],
    *,
    workspace: str,
) -> dict[str, Any]:
    """Build a retry plan for an audit event without executing any tools.

    Args:
        event: The original audit event to analyze.
        workspace: Path to the workspace root for dry gate evaluations.

    Returns:
        A dict with the original event, dry-run decisions per engine,
        recommendations and warnings.
    """
    tool = str(event.get("tool", ""))
    target = str(event.get("target", ""))
    args = parse_target_to_args(tool, target)
    eval_target = _gate_target_for_eval(tool, args)

    ci2lab_gate = evaluate_security_gate(
        engine="ci2lab",
        workspace=workspace,
        tool=tool,
        target=eval_target,
    )
    opencode_gate = evaluate_security_gate(
        engine="opencode_experimental",
        workspace=workspace,
        tool=tool,
        target=eval_target,
    )
    claude_gate = evaluate_security_gate(
        engine="ci2lab_guard",
        workspace=workspace,
        tool=tool,
        target=eval_target,
    )

    recommendations: list[str] = []
    warnings: list[str] = []
    orig_engine = str(event.get("security_engine", ""))
    if event.get("external_directory"):
        warnings.append(_EXTERNAL_WARNING)
    if orig_engine == "ci2lab_guard" and _is_outside_workspace_event(event):
        warnings.append(CI2LAB_GUARD_EXTERNAL_ALLOW_IGNORED)

    if _is_secret_event(event):
        recommendations.extend(
            [
                "Hard block on a sensitive file (secret policy).",
                "Retrying with ci2lab will remain denied.",
                "Allowing reads/writes of secrets is not recommended except under explicit audit.",
                "No unsafe config is generated by default.",
            ]
        )
    elif _is_outside_workspace_event(event):
        recommendations.extend(
            [
                "It was blocked by the hard workspace policy (outside_workspace).",
                "Retrying it with ci2lab will remain denied.",
                "Only opencode_experimental with external_directory=allow could permit it.",
                "That is UNSAFE - do not use in production.",
            ]
        )
    elif orig_engine in {"opencode_experimental", "ci2lab_guard"} and (
        str(event.get("decision", "")).lower() == "ask"
        or event.get("approval_choice") == "deny_once"
    ):
        recommendations.extend(
            [
                f"You can retry with the same {orig_engine} config.",
                "In the interactive prompt choose Allow once or Allow session.",
                "No need to change the permission rules.",
                "You can also use: ci2lab permissions approve-session "
                f"{event.get('event_id')} (only with an active session in this process).",
            ]
        )
    elif orig_engine in {"opencode_experimental", "ci2lab_guard"} and (
        str(event.get("decision", "")).lower() == "deny"
    ):
        matched = str(event.get("matched_rule") or "")
        if matched.startswith("hard:") or (
            orig_engine == "ci2lab_guard" and matched.startswith("hard:")
        ):
            recommendations.extend(
                [
                    "Hard block: cannot be bypassed with permission config or --yes.",
                    "ci2lab_guard keeps the workspace/secret/bash blocklist.",
                ]
            )
        else:
            recommendations.extend(
                [
                    "It was denied by a permission rule (matched_rule).",
                    "--yes / auto_confirm will not bypass this denial.",
                    "You would need to change the permission config to allow it.",
                ]
            )
    else:
        recommendations.append("Review decision, reason and matched_rule of the original event.")
        recommendations.append(f"If you retry with ci2lab: decision={ci2lab_gate['decision']}.")
        recommendations.append(
            f"If you retry with opencode_experimental (defaults): "
            f"decision={opencode_gate['decision']}."
        )
        recommendations.append(
            f"If you retry with ci2lab_guard (defaults): decision={claude_gate['decision']}."
        )

    return {
        "event_id": event.get("event_id"),
        "original": {
            "security_engine": event.get("security_engine"),
            "tool": tool,
            "target": target,
            "decision": event.get("decision"),
            "reason": event.get("reason"),
            "matched_rule": event.get("matched_rule"),
            "external_directory": event.get("external_directory"),
            "hard_guards_enabled": event.get("hard_guards_enabled"),
            "outcome": event.get("outcome"),
            "approval_choice": event.get("approval_choice"),
        },
        "if_retried_ci2lab": ci2lab_gate,
        "if_retried_opencode_experimental": opencode_gate,
        "if_retried_ci2lab_guard": claude_gate,
        "recommendations": recommendations,
        "warnings": warnings,
        "executes_tools": False,
    }


def format_retry_plan(plan: dict[str, Any]) -> str:
    """Render a retry plan (from :func:`build_retry_plan`) as readable text."""
    orig = plan["original"]
    lines = [
        f"Retry plan for event {plan.get('event_id')}",
        "",
        "Original event:",
        f"  engine: {orig.get('security_engine')}",
        f"  tool: {orig.get('tool')}",
        f"  target: {orig.get('target')}",
        f"  decision: {orig.get('decision')}",
        f"  reason: {orig.get('reason')}",
        f"  matched_rule: {orig.get('matched_rule')}",
        f"  external_directory: {orig.get('external_directory')}",
        f"  hard_guards_enabled: {orig.get('hard_guards_enabled')}",
        f"  outcome: {orig.get('outcome')}",
        "",
        "If retried now (dry gate, no execution):",
        f"  ci2lab -> {plan['if_retried_ci2lab']['decision']} "
        f"({plan['if_retried_ci2lab'].get('reason', '')})",
        f"  opencode_experimental -> "
        f"{plan['if_retried_opencode_experimental']['decision']} "
        f"({plan['if_retried_opencode_experimental'].get('reason', '')})",
        f"  ci2lab_guard -> "
        f"{plan['if_retried_ci2lab_guard']['decision']} "
        f"({plan['if_retried_ci2lab_guard'].get('reason', '')})",
        "",
        "Recommendations:",
    ]
    lines.extend(f"  - {rec}" for rec in plan.get("recommendations", []))
    for warn in plan.get("warnings", []):
        lines.extend(["", f"WARNING: {warn}"])
    lines.append("")
    lines.append("(retry-plan does not execute tools)")
    return "\n".join(lines)


def find_latest_audit_file(
    workspace: str | Path,
    *,
    runs_dir: str = "runs",
) -> Path | None:
    """
    Look for security_audit.jsonl under runs/<run_id>/ (most recent by mtime).

    Does not include the `.ci2lab/` fallback - use resolve_audit_source().
    """
    ws = Path(workspace).resolve()
    runs_root = ws / runs_dir
    candidates: list[Path] = []
    if runs_root.is_dir():
        for run_dir in runs_root.iterdir():
            if not run_dir.is_dir():
                continue
            audit = run_dir / "security_audit.jsonl"
            if audit.is_file():
                candidates.append(audit)
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.stat().st_mtime_ns, p.parent.name))


def resolve_audit_source(
    workspace: str | Path,
    *,
    audit_file: str | Path | None = None,
    runs_dir: str = "runs",
) -> tuple[Path, str]:
    """
    Resolve the audit path.

    Precedence: --audit-file > latest run > `.ci2lab/security_audit.jsonl`.
    """
    if audit_file is not None:
        path = Path(audit_file).expanduser().resolve()
        return path, "explicit"

    latest = find_latest_audit_file(workspace, runs_dir=runs_dir)
    if latest is not None:
        return latest, f"run:{latest.parent.name}"

    fallback = resolve_audit_path_within_workspace(
        str(Path(workspace).resolve()),
        runs_dir=runs_dir,
    )
    if fallback.is_file():
        return fallback, "fallback:.ci2lab"
    return fallback, "missing"


def summarize_permissions(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate audit events into summary counters.

    Args:
        events: Normalized audit events to summarize.

    Returns:
        A dict of totals and breakdowns by decision, engine and tool.
    """
    if not events:
        return {
            "total_events": 0,
            "by_decision": {},
            "by_engine": {},
            "by_tool": {},
            "denied_count": 0,
            "asked_count": 0,
            "session_approvals_used": 0,
            "external_directory_count": 0,
            "latest_timestamp": None,
            "run_ids": [],
        }

    by_decision: Counter[str] = Counter()
    by_engine: Counter[str] = Counter()
    by_tool: Counter[str] = Counter()
    run_ids: set[str] = set()
    denied = 0
    asked = 0
    session_used = 0
    external = 0

    for ev in events:
        decision = str(ev.get("decision", ""))
        by_decision[decision] += 1
        by_engine[str(ev.get("security_engine", "unknown"))] += 1
        by_tool[str(ev.get("tool", "unknown"))] += 1
        if ev.get("run_id"):
            run_ids.add(str(ev["run_id"]))
        if _is_denied_event(ev):
            denied += 1
        if decision == "ask":
            asked += 1
        if ev.get("session_approval_used"):
            session_used += 1
        if ev.get("external_directory"):
            external += 1

    timestamps = [str(ev.get("timestamp", "")) for ev in events if ev.get("timestamp")]
    return {
        "total_events": len(events),
        "by_decision": dict(by_decision),
        "by_engine": dict(by_engine),
        "by_tool": dict(by_tool),
        "denied_count": denied,
        "asked_count": asked,
        "session_approvals_used": session_used,
        "external_directory_count": external,
        "latest_timestamp": max(timestamps) if timestamps else None,
        "run_ids": sorted(run_ids),
    }


def _is_denied_event(event: dict[str, Any]) -> bool:
    """Return whether an audit event represents a denied/blocked decision."""
    if str(event.get("decision", "")).lower() == "deny":
        return True
    outcome = str(event.get("outcome", "")).lower()
    return outcome in _DENIED_OUTCOMES


def filter_denied_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the denied/blocked events from ``events``."""
    return [ev for ev in events if _is_denied_event(ev)]


def filter_asked_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the events whose decision was ``ask``."""
    return [ev for ev in events if str(ev.get("decision", "")).lower() == "ask"]


def _truncate(text: str, max_len: int) -> str:
    """Collapse newlines and truncate ``text`` to ``max_len`` chars with an ellipsis."""
    text = text.replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_event_table(events: list[dict[str, Any]], *, max_rows: int = 20) -> str:
    """ASCII table of events (most recent first)."""
    rows = list(reversed(events))[:max_rows]
    if not rows:
        return "(no events)"

    col_names = list(_TABLE_COLUMNS)
    widths = {name: len(name) for name in col_names}
    str_rows: list[dict[str, str]] = []

    for ev in rows:
        row = {
            "event_id": _truncate(str(ev.get("event_id", "")), 12),
            "timestamp": _truncate(str(ev.get("timestamp", ""))[:19], 19),
            "tool": _truncate(str(ev.get("tool", "")), 12),
            "target": _truncate(str(ev.get("target", "")), 40),
            "decision": _truncate(str(ev.get("decision", "")), 8),
            "reason": _truncate(str(ev.get("reason", "")), 24),
            "matched_rule": _truncate(str(ev.get("matched_rule", "") or ""), 20),
            "outcome": _truncate(str(ev.get("outcome", "") or ""), 16),
        }
        str_rows.append(row)
        for key, value in row.items():
            widths[key] = max(widths[key], len(value))

    def fmt_line(values: dict[str, str]) -> str:
        return " | ".join(values[c].ljust(widths[c]) for c in col_names)

    lines = [
        fmt_line({c: c for c in col_names}),
        fmt_line({c: "-" * widths[c] for c in col_names}),
    ]
    lines.extend(fmt_line(r) for r in str_rows)
    if len(events) > max_rows:
        lines.append(f"... ({len(events) - max_rows} older events omitted)")
    return "\n".join(lines)


def format_audit_tail(events: list[dict[str, Any]], *, limit: int = 20) -> str:
    """Last audit lines in compact JSON."""
    tail = events[-limit:] if limit > 0 else events
    return "\n".join(json.dumps(ev, ensure_ascii=False) for ev in tail)
