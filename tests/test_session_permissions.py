"""Tests de session approvals (opencode_experimental)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall
from ci2lab.security.audit import clear_audit_log, get_audit_log
from ci2lab.security.engine import evaluate_tool_gate
from ci2lab.security.opencode_permissions import OpenCodePermissionConfig
from ci2lab.security.session_permissions import (
    ApprovalFingerprint,
    bind_active_session,
    build_approval_fingerprint,
    clear_session_permissions,
    grant_session_approval,
    lookup_session_approval,
    target_fingerprint,
)


@pytest.fixture(autouse=True)
def _reset_session_state():
    clear_session_permissions()
    bind_active_session(None)
    clear_audit_log()
    yield
    clear_session_permissions()
    bind_active_session(None)
    clear_audit_log()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _ask_rules() -> OpenCodePermissionConfig:
    return OpenCodePermissionConfig(rules={"bash": {"*": "ask"}})


def test_allow_session_skips_ask(workspace: Path):
    rules = _ask_rules()
    args = {"command": "echo safe"}
    fp = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args=args,
        matched_rule="bash:*",
        external_directory=False,
    )
    grant_session_approval("sess-1", fp, "allow_session")
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
        session_id="sess-1",
    )
    gate = evaluate_tool_gate("bash", args, config)
    assert gate.proceed
    assert not gate.needs_confirm
    assert gate.reason == "session_allow"
    assert gate.session_approval_used
    assert gate.session_approval_scope == "allow_session"


def test_allow_once_consumed_after_use(workspace: Path):
    rules = _ask_rules()
    args = {"command": "echo once"}
    fp = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args=args,
        matched_rule="bash:*",
        external_directory=False,
    )
    grant_session_approval("sess-1", fp, "allow_once")
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
        session_id="sess-1",
    )
    gate1 = evaluate_tool_gate("bash", args, config)
    assert gate1.reason == "session_allow"
    assert gate1.session_approval_scope == "allow_once"
    gate2 = evaluate_tool_gate("bash", args, config)
    assert gate2.needs_confirm


def test_deny_once_blocks_single_call(workspace: Path):
    rules = _ask_rules()
    args = {"command": "echo blocked"}
    fp = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args=args,
        matched_rule="bash:*",
        external_directory=False,
    )
    grant_session_approval("sess-1", fp, "deny_once")
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
        session_id="sess-1",
    )
    gate1 = evaluate_tool_gate("bash", args, config)
    assert gate1.blocked
    assert gate1.session_approval_scope == "deny_once"
    gate2 = evaluate_tool_gate("bash", args, config)
    assert gate2.needs_confirm


def test_permission_deny_not_overridden_by_session(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"bash": {"*": "deny"}})
    args = {"command": "echo x"}
    fp = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args=args,
        matched_rule="bash:*",
        external_directory=False,
    )
    grant_session_approval("sess-1", fp, "allow_session")
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
        session_id="sess-1",
    )
    gate = evaluate_tool_gate("bash", args, config)
    assert gate.blocked


def test_ci2lab_unaffected_by_session(workspace: Path):
    args = {"command": "echo x"}
    fp = build_approval_fingerprint(
        engine="ci2lab",
        tool_name="bash",
        args=args,
        matched_rule="hard:passed",
        external_directory=False,
    )
    grant_session_approval("sess-1", fp, "allow_session")
    config = AgentConfig(cwd=str(workspace), security_engine="ci2lab", session_id="sess-1")
    gate = evaluate_tool_gate("bash", args, config)
    assert gate.needs_confirm
    assert not gate.session_approval_used


def test_audit_logs_session_approval(workspace: Path):
    rules = _ask_rules()
    args = {"command": "echo audit"}
    fp = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args=args,
        matched_rule="bash:*",
        external_directory=False,
    )
    grant_session_approval("sess-audit", fp, "allow_session")
    execute_tool(
        ToolCall("bash", args, "t1"),
        AgentConfig(
            cwd=str(workspace),
            security_engine="opencode_experimental",
            opencode_permissions=rules,
            session_id="sess-audit",
            auto_confirm=False,
        ),
    )
    entries = get_audit_log()
    assert any(e.extra.get("session_approval_used") for e in entries)
    assert any(e.extra.get("session_approval_scope") == "allow_session" for e in entries)


def test_fingerprint_distinguishes_targets(workspace: Path):
    fp_a = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args={"command": "git status"},
        matched_rule="bash:git *",
        external_directory=False,
    )
    fp_b = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args={"command": "echo other"},
        matched_rule="bash:*",
        external_directory=False,
    )
    assert fp_a != fp_b
    grant_session_approval("sess-1", fp_a, "allow_session")
    assert lookup_session_approval("sess-1", fp_a) == "allow_session"
    assert lookup_session_approval("sess-1", fp_b) is None


def test_fingerprint_normalizes_path_slashes_and_default_dot():
    assert (
        target_fingerprint("write_file", {"path": r"notes\a.txt"})
        == "notes/a.txt"
    )
    assert target_fingerprint("git_status", {}) == "."
    assert target_fingerprint("git_status", {"path": "."}) == "."


def test_git_diff_fingerprint_includes_staged_flag():
    unstaged = target_fingerprint("git_diff", {"path": "."})
    staged = target_fingerprint("git_diff", {"path": ".", "staged": True})

    assert unstaged == ".|staged=False"
    assert staged == ".|staged=True"
    assert unstaged != staged


def test_approval_session_id_skips_ask_without_chat_session(workspace: Path):
    rules = _ask_rules()
    args = {"command": "echo run scoped"}
    fp = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args=args,
        matched_rule="bash:*",
        external_directory=False,
    )
    grant_session_approval("multiagent-run-1", fp, "allow_session")
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
        approval_session_id="multiagent-run-1",
        session_id=None,
    )

    gate = evaluate_tool_gate("bash", args, config)

    assert gate.proceed
    assert not gate.needs_confirm
    assert gate.session_approval_used
    assert gate.session_approval_scope == "allow_session"


def test_approval_session_id_does_not_persist_between_runs(workspace: Path):
    rules = _ask_rules()
    args = {"command": "echo run scoped"}
    fp = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args=args,
        matched_rule="bash:*",
        external_directory=False,
    )
    grant_session_approval("multiagent-run-1", fp, "allow_session")

    gate = evaluate_tool_gate(
        "bash",
        args,
        AgentConfig(
            cwd=str(workspace),
            security_engine="opencode_experimental",
            opencode_permissions=rules,
            approval_session_id="multiagent-run-2",
        ),
    )

    assert gate.needs_confirm
    assert not gate.session_approval_used
