"""`ci2lab permissions` subcommand — CLI dashboard for audit and sessions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ci2lab.security.permissions_dashboard import (
    approval_from_audit_event,
    build_retry_plan,
    filter_asked_events,
    filter_denied_events,
    find_event_by_id,
    format_audit_tail,
    format_event_table,
    format_retry_plan,
    load_audit_events,
    resolve_audit_source,
    summarize_permissions,
)
from ci2lab.security.session_permissions import (
    clear_session_permissions,
    count_session_approvals,
    get_active_session_id,
    grant_session_approval,
    list_session_approvals,
)

console = Console()


def add_permissions_parser(sub: argparse._SubParsersAction) -> None:
    permissions_p = sub.add_parser(
        "permissions",
        help="Permissions dashboard: audit and session approvals",
    )
    perm_sub = permissions_p.add_subparsers(dest="permissions_command", required=True)

    for name, help_text in (
        ("summary", "Summary of decisions in the audit log"),
        ("recent-denied", "Recent denials and blocks"),
        ("recent-asked", "Requests that required confirmation (ask)"),
        ("audit-tail", "Last lines of the audit in JSON"),
        ("session-list", "In-memory session approvals (opencode_experimental)"),
        ("session-clear", "Clear in-memory session approvals"),
    ):
        p = perm_sub.add_parser(name, help=help_text)
        _add_permissions_flags(p)

    session_clear_p = perm_sub.choices["session-clear"]
    session_clear_p.add_argument(
        "--session",
        default=None,
        help="Session ID to clear (default: all)",
    )

    retry_p = perm_sub.add_parser(
        "retry-plan",
        help="Retry plan for an event_id (does not run tools)",
    )
    _add_permissions_flags(retry_p)
    retry_p.add_argument("event_id", help="event_id from the audit")

    approve_p = perm_sub.add_parser(
        "approve-session",
        help="Grant allow_session for an event_id (only the active in-process session)",
    )
    _add_permissions_flags(approve_p)
    approve_p.add_argument("event_id", help="event_id from the audit")


def _add_permissions_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace (default: cwd)",
    )
    p.add_argument(
        "--audit-file",
        type=Path,
        default=None,
        help="Explicit path to security_audit.jsonl",
    )
    p.add_argument(
        "--runs-dir",
        default="runs",
        help="Runs directory to search for the audit (default: runs)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum rows/events to show (default: 20)",
    )
    p.add_argument("--json", action="store_true", help="JSON output")


def cmd_permissions(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace or os.getcwd()).resolve()
    cmd = args.permissions_command

    if cmd in {"session-list", "session-clear"}:
        return _cmd_session(args, cmd)

    if cmd in {"retry-plan", "approve-session"}:
        return _cmd_event_action(args, cmd, workspace)

    audit_path, source = resolve_audit_source(
        workspace,
        audit_file=args.audit_file,
        runs_dir=args.runs_dir,
    )
    if source == "missing" or not audit_path.is_file():
        msg = {
            "error": "security_audit.jsonl not found",
            "workspace": str(workspace),
            "hint": "Run an agent with logging or use --audit-file",
        }
        if args.json:
            console.print_json(json.dumps(msg, ensure_ascii=False))
        else:
            console.print("[yellow]No audit available.[/yellow]")
            console.print(f"  Workspace: {workspace}")
            console.print("  Look in runs/<run_id>/security_audit.jsonl or .ci2lab/")
        return 1

    try:
        events = load_audit_events(audit_path)
    except (ValueError, OSError) as exc:
        if args.json:
            console.print_json(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            console.print(f"[red]Error reading audit:[/red] {exc}")
        return 1

    if cmd == "summary":
        return _print_summary(events, audit_path, source, args)
    if cmd == "recent-denied":
        return _print_filtered(
            filter_denied_events(events),
            title="Recent denials",
            audit_path=audit_path,
            source=source,
            args=args,
        )
    if cmd == "recent-asked":
        return _print_filtered(
            filter_asked_events(events),
            title="Recent ask requests",
            audit_path=audit_path,
            source=source,
            args=args,
        )
    if cmd == "audit-tail":
        return _print_tail(events, audit_path, source, args)

    console.print(f"Unknown subcommand: {cmd}")
    return 1


def _print_summary(
    events: list,
    audit_path: Path,
    source: str,
    args: argparse.Namespace,
) -> int:
    summary = summarize_permissions(events)
    payload = {
        "audit_file": str(audit_path),
        "audit_source": source,
        **summary,
        "session_approvals_in_memory": count_session_approvals(),
        "active_session_id": get_active_session_id(),
    }
    if args.json:
        console.print_json(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    console.print("[bold]Permissions summary[/bold]\n")
    console.print(f"Audit: [cyan]{audit_path}[/cyan] ({source})")
    console.print(f"Total events: {summary['total_events']}")
    if summary["latest_timestamp"]:
        console.print(f"Latest event: {summary['latest_timestamp']}")
    console.print()

    table = Table(title="By decision")
    table.add_column("Decision")
    table.add_column("Count", justify="right")
    for decision, count in sorted(summary["by_decision"].items()):
        table.add_row(decision, str(count))
    console.print(table)
    console.print()

    stats = Table(title="Counters")
    stats.add_column("Metric")
    stats.add_column("Value", justify="right")
    stats.add_row("Denied/blocked", str(summary["denied_count"]))
    stats.add_row("Ask (confirmation)", str(summary["asked_count"]))
    stats.add_row("Session approval used", str(summary["session_approvals_used"]))
    stats.add_row("External paths", str(summary["external_directory_count"]))
    mem = count_session_approvals()
    stats.add_row("In-memory approvals", str(mem["total"]))
    console.print(stats)

    if summary["by_engine"]:
        console.print()
        eng = Table(title="By engine")
        eng.add_column("Engine")
        eng.add_column("Count", justify="right")
        for name, count in sorted(summary["by_engine"].items()):
            eng.add_row(name, str(count))
        console.print(eng)
    return 0


def _print_filtered(
    events: list,
    *,
    title: str,
    audit_path: Path,
    source: str,
    args: argparse.Namespace,
) -> int:
    limit = max(1, args.limit)
    recent = events[-limit:] if len(events) > limit else events

    if args.json:
        payload = {
            "audit_file": str(audit_path),
            "audit_source": source,
            "count": len(events),
            "showing": len(recent),
            "events": recent,
        }
        console.print_json(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]{title}[/bold]")
    console.print(f"Audit: {audit_path} ({source}) — {len(events)} total\n")
    console.print(format_event_table(recent, max_rows=limit))
    return 0


def _print_tail(
    events: list,
    audit_path: Path,
    source: str,
    args: argparse.Namespace,
) -> int:
    limit = max(1, args.limit)
    tail_events = events[-limit:]

    if args.json:
        payload = {
            "audit_file": str(audit_path),
            "audit_source": source,
            "events": tail_events,
        }
        console.print_json(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]Audit tail[/bold] ({source})")
    console.print(f"File: {audit_path}\n")
    console.print(format_audit_tail(events, limit=limit))
    return 0


def _load_audit_or_error(
    workspace: Path,
    args: argparse.Namespace,
) -> tuple[list[dict] | None, Path | None, str | None, int]:
    audit_path, source = resolve_audit_source(
        workspace,
        audit_file=args.audit_file,
        runs_dir=args.runs_dir,
    )
    if source == "missing" or not audit_path.is_file():
        msg = {
            "error": "security_audit.jsonl not found",
            "workspace": str(workspace),
        }
        if args.json:
            console.print_json(json.dumps(msg, ensure_ascii=False))
        else:
            console.print("[yellow]No audit available.[/yellow]")
        return None, None, None, 1
    try:
        events = load_audit_events(audit_path)
    except (ValueError, OSError) as exc:
        if args.json:
            console.print_json(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            console.print(f"[red]Error reading audit:[/red] {exc}")
        return None, None, None, 1
    return events, audit_path, source, 0


def _cmd_event_action(
    args: argparse.Namespace,
    cmd: str,
    workspace: Path,
) -> int:
    events, audit_path, source, code = _load_audit_or_error(workspace, args)
    if code != 0 or events is None:
        return code

    event = find_event_by_id(events, args.event_id)
    if event is None:
        msg = {
            "error": f"event_id not found: {args.event_id!r}",
            "audit_file": str(audit_path),
            "audit_source": source,
        }
        if args.json:
            console.print_json(json.dumps(msg, ensure_ascii=False, indent=2))
        else:
            console.print(f"[red]event_id not found:[/red] {args.event_id}")
            console.print(f"  Audit: {audit_path} ({source})")
        return 1

    if cmd == "retry-plan":
        plan = build_retry_plan(event, workspace=str(workspace))
        plan["audit_file"] = str(audit_path)
        plan["audit_source"] = source
        if args.json:
            console.print_json(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            console.print(format_retry_plan(plan))
        return 0

    try:
        fingerprint, warnings = approval_from_audit_event(event)
    except ValueError as exc:
        payload = {"error": str(exc), "event_id": event.get("event_id")}
        if args.json:
            console.print_json(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            console.print(f"[red]Cannot approve:[/red] {exc}")
        return 1

    active = get_active_session_id()
    if not active:
        msg = {
            "error": "no_active_session",
            "message": (
                "Cannot affect a previous finished process: session approvals "
                "are in-memory only. Use this command only inside an active "
                "CI2Lab session, or retry manually with retry-plan."
            ),
            "event_id": event.get("event_id"),
            "warnings": warnings,
        }
        if args.json:
            console.print_json(json.dumps(msg, ensure_ascii=False, indent=2))
        else:
            console.print("[yellow]Cannot affect a previous finished process: "
                          "session approvals are in-memory only.[/yellow]")
            console.print(
                "Use this command only inside an active CI2Lab session, "
                "or retry manually with retry-plan."
            )
            for warn in warnings:
                console.print(f"[yellow]WARNING:[/yellow] {warn}")
        return 1

    grant_session_approval(active, fingerprint, "allow_session")
    payload = {
        "approved": True,
        "scope": "allow_session",
        "session_key": active,
        "event_id": event.get("event_id"),
        "tool": event.get("tool"),
        "target": event.get("target"),
        "matched_rule": event.get("matched_rule"),
        "warnings": warnings,
    }
    if args.json:
        console.print_json(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console.print(
            f"[green]allow_session recorded[/green] for session {active!r}"
        )
        console.print(
            f"  tool={event.get('tool')} rule={event.get('matched_rule')}"
        )
        for warn in warnings:
            console.print(f"[yellow]WARNING:[/yellow] {warn}")
    return 0


def _cmd_session(args: argparse.Namespace, cmd: str) -> int:
    if cmd == "session-clear":
        target = args.session
        clear_session_permissions(target)
        if args.json:
            console.print_json(
                json.dumps(
                    {
                        "cleared": True,
                        "session": target or "*",
                        "remaining": count_session_approvals(),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            scope = f"session {target!r}" if target else "all sessions"
            console.print(f"[green]Approvals cleared[/green] ({scope})")
        return 0

    rows = list_session_approvals(args.session)
    if args.json:
        console.print_json(
            json.dumps(
                {
                    "active_session_id": get_active_session_id(),
                    "count": len(rows),
                    "approvals": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    console.print("[bold]Session approvals[/bold] (process memory)\n")
    console.print(
        "[dim]opencode_experimental only. Does not persist between processes.[/dim]\n"
    )
    active = get_active_session_id()
    if active:
        console.print(f"Active session in this process: [cyan]{active}[/cyan]")
    else:
        console.print("No active session in this process.")

    if not rows:
        console.print("\n(empty — no approvals in memory)")
        return 0

    table = Table()
    table.add_column("Session")
    table.add_column("Scope")
    table.add_column("Tool")
    table.add_column("Rule")
    table.add_column("Target")
    for row in rows[: max(1, args.limit)]:
        table.add_row(
            row["session_key"][:20],
            row["scope"],
            row["tool"],
            row["matched_rule"][:24],
            row["target"][:40],
        )
    console.print()
    console.print(table)
    if len(rows) > args.limit:
        console.print(f"... {len(rows) - args.limit} more")
    return 0
