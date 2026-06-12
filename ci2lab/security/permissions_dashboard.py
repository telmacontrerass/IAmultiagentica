"""Lectura y resumen de auditoría de permisos (dashboard CLI tipo /permissions)."""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ci2lab.security.audit import resolve_audit_path_within_workspace
from ci2lab.security.engine import CLAUDE_EXTERNAL_ALLOW_IGNORED, uses_permission_layer
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

_EXTERNAL_WARNING = (
    "INSEGURO: external_directory=true — acceso fuera del workspace"
)

_DENIED_OUTCOMES = frozenset({
    "blocked",
    "blocked_by_workspace",
    "blocked_by_secret_policy",
    "blocked_by_security_profile",
    "blocked_by_config",
    "denied",
    "error",
})


def load_audit_events(path: str | Path) -> list[dict[str, Any]]:
    """Carga eventos JSONL. Líneas inválidas se omiten con aviso implícito."""
    audit_path = Path(path).expanduser().resolve()
    if not audit_path.is_file():
        raise FileNotFoundError(f"No existe el archivo de auditoría: {audit_path}")

    events: list[dict[str, Any]] = []
    for line_no, raw in enumerate(
        audit_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"JSON inválido en {audit_path}:{line_no}: {exc}"
            ) from exc
        if not isinstance(record, dict):
            raise ValueError(
                f"Línea {line_no} en {audit_path}: debe ser un objeto JSON."
            )
        events.append(_normalize_event(record))
    return events


def compute_event_id(record: dict[str, Any]) -> str:
    """ID estable derivado de campos del evento (12 hex chars)."""
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
    """Unifica campos legacy y anidados."""
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
    needle = event_id.strip().lower()
    for ev in events:
        if str(ev.get("event_id", "")).lower() == needle:
            return ev
    return None


def parse_target_to_args(tool: str, target: str) -> dict[str, Any]:
    """Reconstruye args mínimos desde tool + target del audit."""
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
    if tool in {"bash", "shell"}:
        return str(args.get("command", ""))
    if tool in {"grep", "glob"}:
        return str(args.get("pattern", args.get("path", "")))
    return str(args.get("path", ""))


def approval_from_audit_event(
    event: dict[str, Any],
) -> tuple[ApprovalFingerprint, list[str]]:
    """
    Construye fingerprint para approve-session.

    Raises ValueError si el evento no es elegible.
    """
    warnings: list[str] = []
    engine = str(event.get("security_engine", ""))
    if engine == "ci2lab":
        raise ValueError(
            "approve-session no aplica a ci2lab; use motores permission-layer."
        )
    if not uses_permission_layer(engine):
        raise ValueError(f"Motor no soportado para approve-session: {engine!r}")

    decision = str(event.get("decision", "")).lower()
    approval_choice = event.get("approval_choice")
    if decision == "deny":
        matched = str(event.get("matched_rule") or "")
        if matched.startswith("hard:"):
            raise ValueError(
                "No se puede aprobar: bloqueo hard (workspace/secret/bash/profile). "
                "Cambiar permission config no lo saltará."
            )
        raise ValueError(
            "No se puede aprobar: el evento fue denegado por regla de permission."
        )
    if decision != "ask" and approval_choice != "deny_once":
        raise ValueError(
            "approve-session solo aplica a eventos con decision=ask "
            "o approval_choice=deny_once."
        )

    tool = event.get("tool")
    target = event.get("target")
    if not tool or target is None or str(target).strip() == "":
        raise ValueError(
            "Faltan campos tool/target para construir el fingerprint."
        )

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
    """Plan de reintento sin ejecutar tools."""
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
        engine="claude_experimental",
        workspace=workspace,
        tool=tool,
        target=eval_target,
    )

    recommendations: list[str] = []
    warnings: list[str] = []
    orig_engine = str(event.get("security_engine", ""))
    if event.get("external_directory"):
        warnings.append(_EXTERNAL_WARNING)
    if orig_engine == "claude_experimental" and _is_outside_workspace_event(event):
        warnings.append(CLAUDE_EXTERNAL_ALLOW_IGNORED)

    if _is_secret_event(event):
        recommendations.extend(
            [
                "Bloqueo duro de archivo sensible (secret policy).",
                "Reintentar con ci2lab seguirá denegado.",
                "No se recomienda permitir lectura/escritura de secretos "
                "salvo auditoría explícita.",
                "No se genera config insegura por defecto.",
            ]
        )
    elif _is_outside_workspace_event(event):
        recommendations.extend(
            [
                "Fue bloqueado por política dura de workspace (outside_workspace).",
                "Reintentarlo con ci2lab seguirá siendo denegado.",
                "Solo opencode_experimental con external_directory=allow "
                "podría permitirlo.",
                "Eso es INSEGURO — no usar en producción.",
            ]
        )
    elif orig_engine in {"opencode_experimental", "claude_experimental"} and (
        str(event.get("decision", "")).lower() == "ask"
        or event.get("approval_choice") == "deny_once"
    ):
        recommendations.extend(
            [
                f"Puedes reintentar con la misma config {orig_engine}.",
                "En el prompt interactivo elige Allow once o Allow session.",
                "No hace falta cambiar las reglas de permission.",
                "También puedes usar: ci2lab permissions approve-session "
                f"{event.get('event_id')} (solo con sesión activa en este proceso).",
            ]
        )
    elif orig_engine in {"opencode_experimental", "claude_experimental"} and (
        str(event.get("decision", "")).lower() == "deny"
    ):
        matched = str(event.get("matched_rule") or "")
        if matched.startswith("hard:") or orig_engine == "claude_experimental" and matched.startswith("hard:"):
            recommendations.extend(
                [
                    "Bloqueo hard: no se puede saltar con permission config ni --yes.",
                    "claude_experimental mantiene workspace/secret/bash blocklist.",
                ]
            )
        else:
            recommendations.extend(
                [
                    "Fue denegado por regla de permission (matched_rule).",
                    "--yes / auto_confirm no saltará esta denegación.",
                    "Habría que cambiar la permission config para permitirlo.",
                ]
            )
    else:
        recommendations.append(
            "Revisa decision, reason y matched_rule del evento original."
        )
        recommendations.append(
            f"Si reintentas con ci2lab: decision={ci2lab_gate['decision']}."
        )
        recommendations.append(
            f"Si reintentas con opencode_experimental (defaults): "
            f"decision={opencode_gate['decision']}."
        )
        recommendations.append(
            f"Si reintentas con claude_experimental (defaults): "
            f"decision={claude_gate['decision']}."
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
        "if_retried_claude_experimental": claude_gate,
        "recommendations": recommendations,
        "warnings": warnings,
        "executes_tools": False,
    }


def format_retry_plan(plan: dict[str, Any]) -> str:
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
        f"  claude_experimental -> "
        f"{plan['if_retried_claude_experimental']['decision']} "
        f"({plan['if_retried_claude_experimental'].get('reason', '')})",
        "",
        "Recommendations:",
    ]
    lines.extend(f"  - {rec}" for rec in plan.get("recommendations", []))
    for warn in plan.get("warnings", []):
        lines.extend(["", f"WARNING: {warn}"])
    lines.append("")
    lines.append("(retry-plan no ejecuta herramientas)")
    return "\n".join(lines)


def find_latest_audit_file(
    workspace: str | Path,
    *,
    runs_dir: str = "runs",
) -> Path | None:
    """
    Busca security_audit.jsonl en runs/<run_id>/ (más reciente por mtime).

    No incluye el fallback `.ci2lab/` — usar resolve_audit_source().
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
    Resuelve ruta de auditoría.

    Precedencia: --audit-file > último run > `.ci2lab/security_audit.jsonl`.
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
    if str(event.get("decision", "")).lower() == "deny":
        return True
    outcome = str(event.get("outcome", "")).lower()
    return outcome in _DENIED_OUTCOMES


def filter_denied_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [ev for ev in events if _is_denied_event(ev)]


def filter_asked_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [ev for ev in events if str(ev.get("decision", "")).lower() == "ask"]


def _truncate(text: str, max_len: int) -> str:
    text = text.replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_event_table(events: list[dict[str, Any]], *, max_rows: int = 20) -> str:
    """Tabla ASCII de eventos (más recientes primero)."""
    rows = list(reversed(events))[:max_rows]
    if not rows:
        return "(sin eventos)"

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
        lines.append(f"... ({len(events) - max_rows} eventos más antiguos omitidos)")
    return "\n".join(lines)


def format_audit_tail(events: list[dict[str, Any]], *, limit: int = 20) -> str:
    """Últimas líneas del audit en JSON compacto."""
    tail = events[-limit:] if limit > 0 else events
    return "\n".join(json.dumps(ev, ensure_ascii=False) for ev in tail)
