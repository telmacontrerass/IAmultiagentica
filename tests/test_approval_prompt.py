"""Tests del prompt interactivo OpenCode (P2.5)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall
from ci2lab.security.approval_prompt import (
    ApprovalChoice,
    OpenCodeApprovalDecision,
    confirm_opencode_ask,
    parse_approval_choice,
    prompt_opencode_approval,
)
from ci2lab.security.engine import ToolGateResult, evaluate_tool_gate
from ci2lab.security.opencode_permissions import OpenCodePermissionConfig
from ci2lab.security.session_permissions import clear_session_permissions


@pytest.fixture(autouse=True)
def _reset_sessions():
    clear_session_permissions()
    yield
    clear_session_permissions()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def test_parse_approval_choice_aliases():
    assert parse_approval_choice("a") == ApprovalChoice.ALLOW_ONCE
    assert parse_approval_choice("session") == ApprovalChoice.ALLOW_SESSION
    assert parse_approval_choice("d") == ApprovalChoice.DENY_ONCE
    assert parse_approval_choice("cancel") == ApprovalChoice.ABORT


def test_prompt_opencode_approval_allow_session():
    out = StringIO()
    choice = prompt_opencode_approval(
        OpenCodeApprovalDecision(
            tool_name="bash",
            target_summary="echo safe",
            matched_rule="bash:*",
        ),
        input_func=lambda _: "s",
        output_func=out.write,
    )
    assert choice == ApprovalChoice.ALLOW_SESSION
    assert "opencode_experimental" in out.getvalue()


def test_prompt_empty_input_aborts():
    choice = prompt_opencode_approval(
        OpenCodeApprovalDecision(tool_name="bash", target_summary="x"),
        input_func=lambda _: "   ",
        output_func=lambda _: None,
    )
    assert choice == ApprovalChoice.ABORT


def test_confirm_auto_confirm_skips_prompt(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"bash": {"*": "ask"}})
    args = {"command": "echo safe"}
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
        auto_confirm=True,
        session_id="s1",
    )
    gate = evaluate_tool_gate("bash", args, config)
    result = confirm_opencode_ask(
        config=config,
        tool_name="bash",
        args=args,
        gate=gate,
        detail="echo safe",
        input_func=lambda _: pytest.fail("no prompt"),
    )
    assert result.proceed
    assert result.reason == "auto_confirm"


def test_confirm_allow_session_grants_and_proceeds(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"bash": {"*": "ask"}})
    args = {"command": "echo safe"}
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
        session_id="sess-prompt",
    )
    gate = evaluate_tool_gate("bash", args, config)
    assert gate.needs_confirm
    result = confirm_opencode_ask(
        config=config,
        tool_name="bash",
        args=args,
        gate=gate,
        detail="echo safe",
        input_func=lambda _: "allow_session",
    )
    assert result.proceed
    assert result.session_scope_granted == "allow_session"

    gate2 = evaluate_tool_gate("bash", args, config)
    assert not gate2.needs_confirm
    assert gate2.session_approval_used


def test_confirm_deny_once_blocks_next_ask(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"bash": {"*": "ask"}})
    args = {"command": "echo deny"}
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
        session_id="sess-deny",
    )
    gate = evaluate_tool_gate("bash", args, config)
    result = confirm_opencode_ask(
        config=config,
        tool_name="bash",
        args=args,
        gate=gate,
        detail="echo deny",
        input_func=lambda _: "d",
    )
    assert not result.proceed
    assert result.choice == ApprovalChoice.DENY_ONCE

    gate2 = evaluate_tool_gate("bash", args, config)
    assert gate2.blocked
    assert gate2.session_approval_scope == "deny_once"


def test_execute_tool_opencode_allow_once_runs(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"bash": {"*": "ask"}})
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
        session_id="exec-once",
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "ci2lab.security.approval_prompt.prompt_opencode_approval",
            lambda *a, **k: ApprovalChoice.ALLOW_ONCE,
        )
        result = execute_tool(
            ToolCall("bash", {"command": "echo ok"}, "t1"),
            config,
        )
    assert not result.is_error
    assert "ok" in result.content or result.content.strip() != ""


def test_execute_tool_ci2lab_uses_legacy_confirm(workspace: Path, monkeypatch):
    monkeypatch.setattr(
        "ci2lab.harness.permissions.default_confirm",
        lambda tool, summary: True,
    )
    config = AgentConfig(cwd=str(workspace), security_engine="ci2lab")
    result = execute_tool(
        ToolCall("bash", {"command": "echo legacy"}, "t1"),
        config,
    )
    assert not result.is_error


def test_permission_deny_never_prompted(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"bash": {"*": "deny"}})
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
    )
    result = execute_tool(
        ToolCall("bash", {"command": "echo x"}, "t1"),
        config,
    )
    assert result.is_error
    assert result.outcome == "blocked_by_permission"
