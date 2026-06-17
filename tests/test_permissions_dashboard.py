"""Tests P2.7 — permissions dashboard CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ci2lab.security.permissions_dashboard import (
    filter_asked_events,
    filter_denied_events,
    find_latest_audit_file,
    format_event_table,
    load_audit_events,
    resolve_audit_source,
    summarize_permissions,
)
from ci2lab.security.session_permissions import (
    build_approval_fingerprint,
    clear_session_permissions,
    grant_session_approval,
    list_session_approvals,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _write_audit(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(ev, ensure_ascii=False) for ev in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_audit_events(workspace: Path):
    audit = workspace / "runs" / "run-a" / "security_audit.jsonl"
    _write_audit(
        audit,
        [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "tool": "bash",
                "target": "git status",
                "decision": "allow",
                "reason": "ok",
                "outcome": "executed",
                "security_engine": "opencode_experimental",
            }
        ],
    )
    events = load_audit_events(audit)
    assert len(events) == 1
    assert events[0]["tool"] == "bash"


def test_find_latest_audit_file_prefers_newer_run(workspace: Path):
    old = workspace / "runs" / "2026-01-01_old" / "security_audit.jsonl"
    new = workspace / "runs" / "2026-01-02_new" / "security_audit.jsonl"
    _write_audit(old, [{"tool": "a", "decision": "allow", "target": "x"}])
    _write_audit(new, [{"tool": "b", "decision": "allow", "target": "y"}])
    new.touch()
    found = find_latest_audit_file(workspace)
    assert found == new


def test_resolve_audit_source_fallback(workspace: Path):
    fallback = workspace / ".ci2lab" / "security_audit.jsonl"
    _write_audit(fallback, [{"tool": "ls", "decision": "allow", "target": "."}])
    path, source = resolve_audit_source(workspace)
    assert path == fallback.resolve()
    assert source == "fallback:.ci2lab"


def test_summarize_and_filters(workspace: Path):
    events = [
        {"decision": "allow", "tool": "ls", "security_engine": "ci2lab", "outcome": "executed"},
        {"decision": "deny", "tool": "bash", "security_engine": "ci2lab", "outcome": "blocked_by_workspace"},
        {"decision": "ask", "tool": "bash", "security_engine": "opencode_experimental", "outcome": "pending"},
        {
            "decision": "allow",
            "tool": "read_file",
            "security_engine": "opencode_experimental",
            "session_approval_used": True,
            "external_directory": True,
            "outcome": "executed",
        },
    ]
    summary = summarize_permissions(events)
    assert summary["total_events"] == 4
    assert summary["denied_count"] == 1
    assert summary["asked_count"] == 1
    assert summary["session_approvals_used"] == 1
    assert summary["external_directory_count"] == 1
    assert len(filter_denied_events(events)) == 1
    assert len(filter_asked_events(events)) == 1


def test_format_event_table():
    text = format_event_table(
        [{"timestamp": "t", "tool": "bash", "target": "x", "decision": "deny", "reason": "r", "outcome": "blocked"}],
        max_rows=5,
    )
    assert "bash" in text
    assert "deny" in text


def test_session_list_in_memory(workspace: Path):
    clear_session_permissions()
    fp = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args={"command": "echo hi"},
        matched_rule="bash:*",
        external_directory=False,
    )
    grant_session_approval("sess-dash", fp, "allow_session")
    rows = list_session_approvals("sess-dash")
    assert len(rows) == 1
    assert rows[0]["scope"] == "allow_session"
    clear_session_permissions()


def test_cli_permissions_summary(workspace: Path):
    audit = workspace / ".ci2lab" / "security_audit.jsonl"
    _write_audit(
        audit,
        [
            {
                "timestamp": "2026-06-10T12:00:00+00:00",
                "tool": "bash",
                "target": "rm *",
                "decision": "deny",
                "reason": "blocked",
                "outcome": "blocked",
                "security_engine": "opencode_experimental",
            }
        ],
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ci2lab",
            "permissions",
            "summary",
            "--workspace",
            str(workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["total_events"] == 1
    assert data["denied_count"] == 1


def test_cli_recent_denied(workspace: Path):
    audit = workspace / ".ci2lab" / "security_audit.jsonl"
    _write_audit(
        audit,
        [
            {"tool": "a", "target": "1", "decision": "allow", "outcome": "executed"},
            {"tool": "b", "target": "2", "decision": "deny", "outcome": "denied", "reason": "x"},
        ],
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ci2lab",
            "permissions",
            "recent-denied",
            "--workspace",
            str(workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["count"] == 1


def test_cli_session_list_json():
    clear_session_permissions()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ci2lab",
            "permissions",
            "session-list",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert "approvals" in data
    clear_session_permissions()


def test_invalid_audit_json_fails(workspace: Path):
    bad = workspace / "bad.jsonl"
    bad.write_text("{broken\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_audit_events(bad)
