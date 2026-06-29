"""Tests del selector de motor de seguridad CI2Lab vs OpenCode experimental."""

from __future__ import annotations

from pathlib import Path

import pytest

from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall
from ci2lab.security.audit import clear_audit_log, get_audit_log
from ci2lab.security.engine import (
    SecurityEngineName,
    enforce_ci2lab_hard_policy,
    evaluate_tool_gate,
    normalize_security_engine,
)
from ci2lab.security.opencode_permissions import (
    OpenCodePermissionConfig,
    evaluate_opencode_tool,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "inside.txt").write_text("inside\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside-data\n", encoding="utf-8")
    return ws


@pytest.fixture
def outside_secret(tmp_path: Path) -> Path:
    return (tmp_path / "outside" / "secret.txt").resolve()


@pytest.fixture(autouse=True)
def _clear_audit():
    clear_audit_log()
    yield
    clear_audit_log()


def test_default_engine_is_claude_experimental():
    assert normalize_security_engine(None) == SecurityEngineName.CLAUDE_EXPERIMENTAL.value
    assert normalize_security_engine("standard") == SecurityEngineName.CI2LAB.value


def test_opencode_engine_normalized():
    assert normalize_security_engine("opencode") == SecurityEngineName.OPENCODE_EXPERIMENTAL.value


def test_ci2lab_blocks_external_read(workspace: Path, outside_secret: Path):
    config = AgentConfig(cwd=str(workspace), security_engine="ci2lab")
    gate = evaluate_tool_gate("read_file", {"path": str(outside_secret)}, config)
    assert gate.blocked
    assert gate.outcome == "blocked_by_workspace"


def test_opencode_experimental_allows_external_read_with_allow_rule(
    workspace: Path, outside_secret: Path
):
    rules = OpenCodePermissionConfig(
        rules={
            "read": {"*": "allow"},
            "external_directory": {"*": "allow"},
        }
    )
    decision = evaluate_opencode_tool(
        "read_file",
        {"path": str(outside_secret)},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "allow"

    config = AgentConfig(
        cwd=str(workspace),
        security_engine="opencode_experimental",
        opencode_permissions=rules,
        auto_confirm=True,
    )
    result = execute_tool(
        ToolCall("read_file", {"path": str(outside_secret)}, "t1"),
        config,
    )
    assert not result.is_error
    assert "outside-data" in result.content


def test_ci2lab_yes_still_blocks_external(workspace: Path, outside_secret: Path):
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="ci2lab",
        auto_confirm=True,
    )
    result = execute_tool(
        ToolCall("read_file", {"path": str(outside_secret)}, "t1"),
        config,
    )
    assert result.is_error
    assert result.outcome == "blocked_by_workspace"


def test_opencode_bash_rm_denied_by_default(workspace: Path):
    rules = OpenCodePermissionConfig.default_experimental()
    decision = evaluate_opencode_tool(
        "bash",
        {"command": "rm -rf /"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=True,
    )
    assert decision.action.value == "deny"


def test_opencode_git_allow(workspace: Path):
    rules = OpenCodePermissionConfig.default_experimental()
    decision = evaluate_opencode_tool(
        "bash",
        {"command": "git status"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=True,
    )
    assert decision.action.value == "allow"


def test_audit_logs_engine(workspace: Path, outside_secret: Path):
    execute_tool(
        ToolCall("read_file", {"path": str(outside_secret)}, "t1"),
        AgentConfig(cwd=str(workspace), security_engine="ci2lab"),
    )
    entries = get_audit_log()
    assert entries
    assert entries[0].decision == "deny"
    assert entries[0].extra.get("engine") == "ci2lab"


def test_enforce_ci2lab_hard_policy_flag():
    assert enforce_ci2lab_hard_policy("ci2lab") is True
    assert enforce_ci2lab_hard_policy("claude_experimental") is True
    assert enforce_ci2lab_hard_policy("opencode_experimental") is False
