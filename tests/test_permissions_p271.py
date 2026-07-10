"""Tests P2.7.1 - event_id, retry-plan, approve-session."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ci2lab.security.permissions_dashboard import (
    approval_from_audit_event,
    build_retry_plan,
    compute_event_id,
    find_event_by_id,
    format_event_table,
    load_audit_events,
)
from ci2lab.security.session_permissions import (
    bind_active_session,
    clear_session_permissions,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _base_event(**overrides) -> dict:
    ev = {
        "timestamp": "2026-06-10T12:00:00+00:00",
        "run_id": "run-1",
        "tool": "bash",
        "target": "git status",
        "decision": "allow",
        "reason": "ok",
        "matched_rule": "bash:git *",
        "security_engine": "opencode_experimental",
    }
    ev.update(overrides)
    return ev


def test_same_event_same_event_id():
    a = _base_event()
    b = _base_event()
    assert compute_event_id(a) == compute_event_id(b)
    assert len(compute_event_id(a)) == 12


def test_different_events_different_ids():
    a = _base_event(target="git status")
    b = _base_event(target="rm *")
    assert compute_event_id(a) != compute_event_id(b)


def test_load_audit_assigns_event_id(workspace: Path):
    audit = workspace / "audit.jsonl"
    audit.write_text(
        json.dumps(_base_event()) + "\n",
        encoding="utf-8",
    )
    events = load_audit_events(audit)
    assert events[0]["event_id"]
    assert len(events[0]["event_id"]) == 12


def test_recent_denied_shows_event_id(workspace: Path):
    audit = workspace / ".ci2lab" / "security_audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    ev = _base_event(decision="deny", outcome="denied", reason="blocked")
    audit.write_text(json.dumps(ev) + "\n", encoding="utf-8")
    events = load_audit_events(audit)
    table = format_event_table(events)
    assert events[0]["event_id"] in table


def test_audit_tail_json_includes_event_id(workspace: Path):
    audit = workspace / ".ci2lab" / "security_audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps(_base_event()) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ci2lab",
            "permissions",
            "audit-tail",
            "--workspace",
            str(workspace),
            "--limit",
            "5",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["events"][0]["event_id"]


def test_retry_plan_does_not_execute_tools(workspace: Path):
    event = load_audit_events(
        _write_audit_file(
            workspace,
            _base_event(decision="deny", outcome="blocked_by_workspace"),
        )
    )[0]
    with patch("ci2lab.security.permissions_dashboard.evaluate_security_gate") as mock_gate:
        mock_gate.return_value = {"decision": "deny", "reason": "mock"}
        plan = build_retry_plan(event, workspace=str(workspace))
        assert plan["executes_tools"] is False
        assert mock_gate.call_count == 3


def _write_audit_file(workspace: Path, event: dict) -> Path:
    audit = workspace / ".ci2lab" / "security_audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps(event) + "\n", encoding="utf-8")
    return audit


def test_retry_plan_outside_workspace(workspace: Path):
    event = load_audit_events(
        _write_audit_file(
            workspace,
            {
                **_base_event(
                    tool="read_file",
                    target="/outside/secret.txt",
                    decision="deny",
                    reason="outside_workspace",
                    matched_rule="hard:outside_workspace",
                    outcome="blocked_by_workspace",
                    security_engine="ci2lab",
                    hard_guards_enabled=True,
                    external_directory=True,
                )
            },
        )
    )[0]
    plan = build_retry_plan(event, workspace=str(workspace))
    text = " ".join(plan["recommendations"]).lower()
    assert "workspace" in text
    assert "ci2lab" in text
    assert "unsafe" in text or "external_directory" in text.lower()
    assert plan["warnings"]


def test_retry_plan_opencode_ask(workspace: Path):
    event = load_audit_events(
        _write_audit_file(
            workspace,
            _base_event(
                decision="ask",
                outcome="pending",
                approval_choice="deny_once",
            ),
        )
    )[0]
    plan = build_retry_plan(event, workspace=str(workspace))
    text = " ".join(plan["recommendations"]).lower()
    assert "allow once" in text or "allow session" in text
    assert "same" in text and "config" in text


def test_retry_plan_deny_rule(workspace: Path):
    event = load_audit_events(
        _write_audit_file(
            workspace,
            _base_event(
                decision="deny",
                reason="permission_deny:bash:rm *",
                matched_rule="bash:rm *",
                outcome="blocked_by_permission",
            ),
        )
    )[0]
    plan = build_retry_plan(event, workspace=str(workspace))
    text = " ".join(plan["recommendations"]).lower()
    assert "permission" in text
    assert "--yes" in text or "auto_confirm" in text


def test_retry_plan_missing_event_id(workspace: Path):
    _write_audit_file(workspace, _base_event())
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ci2lab",
            "permissions",
            "retry-plan",
            "deadbeef0000",
            "--workspace",
            str(workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert "error" in data


def test_approval_from_audit_opencode_ask():
    event = {
        "security_engine": "opencode_experimental",
        "decision": "ask",
        "tool": "bash",
        "target": "echo safe",
        "matched_rule": "bash:*",
        "hard_guards_enabled": False,
        "external_directory": False,
    }
    fp, warnings = approval_from_audit_event(event)
    assert fp.tool_canonical == "bash"
    assert fp.target_fingerprint == "echo safe"
    assert not warnings


def test_approval_ci2lab_rejected():
    with pytest.raises(ValueError, match="ci2lab"):
        approval_from_audit_event(
            {
                "security_engine": "ci2lab",
                "decision": "ask",
                "tool": "bash",
                "target": "x",
                "matched_rule": "x",
                "hard_guards_enabled": True,
            }
        )


def test_approval_hard_guards_rejected():
    with pytest.raises(ValueError, match="hard block"):
        approval_from_audit_event(
            {
                "security_engine": "ci2lab_guard",
                "decision": "deny",
                "tool": "read_file",
                "target": "../outside.txt",
                "matched_rule": "hard:outside_workspace",
                "hard_guards_enabled": True,
            }
        )


def test_approval_deny_rule_rejected():
    with pytest.raises(ValueError, match="denied"):
        approval_from_audit_event(
            {
                "security_engine": "opencode_experimental",
                "decision": "deny",
                "tool": "bash",
                "target": "rm *",
                "matched_rule": "bash:rm *",
                "hard_guards_enabled": False,
            }
        )


def test_approval_missing_fields():
    with pytest.raises(ValueError, match="Missing tool/target"):
        approval_from_audit_event(
            {
                "security_engine": "opencode_experimental",
                "decision": "ask",
                "hard_guards_enabled": False,
            }
        )


def test_approval_external_warning():
    _, warnings = approval_from_audit_event(
        {
            "security_engine": "opencode_experimental",
            "decision": "ask",
            "tool": "read_file",
            "target": "../outside.txt",
            "matched_rule": "read:*",
            "hard_guards_enabled": False,
            "external_directory": True,
        }
    )
    assert any("external_directory" in w for w in warnings)


def test_approve_session_no_active_session(workspace: Path):
    clear_session_permissions()
    bind_active_session(None)
    audit = _write_audit_file(
        workspace,
        _base_event(decision="ask", outcome="pending"),
    )
    event = load_audit_events(audit)[0]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ci2lab",
            "permissions",
            "approve-session",
            event["event_id"],
            "--workspace",
            str(workspace),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 1
    assert "in-memory only" in proc.stdout.lower() or "Cannot affect" in proc.stdout


def test_approve_session_with_active_session(workspace: Path):
    clear_session_permissions()
    bind_active_session("sess-live")
    try:
        audit = _write_audit_file(
            workspace,
            _base_event(decision="ask", outcome="pending"),
        )
        event = load_audit_events(audit)[0]
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "ci2lab",
                "permissions",
                "approve-session",
                event["event_id"],
                "--workspace",
                str(workspace),
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        # Subprocess has its own memory - expect no active session in child
        assert proc.returncode == 1
    finally:
        bind_active_session(None)
        clear_session_permissions()


def test_find_event_by_id_roundtrip(workspace: Path):
    audit = _write_audit_file(workspace, _base_event())
    events = load_audit_events(audit)
    eid = events[0]["event_id"]
    assert find_event_by_id(events, eid) is not None
