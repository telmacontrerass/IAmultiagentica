"""Tests de la capa central ci2lab.security."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ci2lab.harness.parsing import resolve_tool_calls
from ci2lab.harness.tools.bash import run_bash
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.security import (
    DecisionAction,
    PathViolationError,
    assert_within_workspace,
    check_command_allowed,
    check_path_allowed,
    clear_audit_log,
    get_audit_log,
    resolve_workspace_path,
)
from ci2lab.harness.types import AgentConfig, ToolCall


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "inside.txt").write_text("inside-content\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside-secret\n", encoding="utf-8")
    return ws


@pytest.fixture
def outside_secret(tmp_path: Path) -> Path:
    return (tmp_path / "outside" / "secret.txt").resolve()


@pytest.fixture(autouse=True)
def _clear_audit():
    clear_audit_log()
    yield
    clear_audit_log()


def test_read_inside_workspace(workspace: Path):
    resolved = resolve_workspace_path(str(workspace), "inside.txt")
    assert resolved.name == "inside.txt"
    decision = check_path_allowed(str(workspace), "inside.txt")
    assert decision.action is DecisionAction.ALLOW


def test_block_read_outside_workspace(workspace: Path, outside_secret: Path):
    decision = check_path_allowed(str(workspace), str(outside_secret))
    assert decision.action is DecisionAction.DENY
    assert decision.outcome == "blocked_by_workspace"


def test_write_inside_workspace(workspace: Path):
    target = workspace / "new.txt"
    resolved = assert_within_workspace(str(workspace), "new.txt")
    assert resolved.parent == workspace.resolve()
    assert not target.exists()


def test_block_write_outside_workspace(workspace: Path, outside_secret: Path):
    with pytest.raises(PathViolationError, match="fuera del workspace"):
        assert_within_workspace(str(workspace), str(outside_secret))


def test_block_dotdot_escape(workspace: Path):
    with pytest.raises(PathViolationError):
        resolve_workspace_path(str(workspace), "../outside/secret.txt")


def test_bash_destructive_blocked(workspace: Path):
    decision = check_command_allowed("rm -rf /", str(workspace))
    assert decision.action is DecisionAction.DENY


def test_bash_external_path_blocked(workspace: Path, outside_secret: Path):
    cmd = f"type {outside_secret}"
    decision = check_command_allowed(cmd, str(workspace))
    assert decision.action is DecisionAction.DENY


def test_yes_does_not_bypass_workspace(workspace: Path, outside_secret: Path):
    config = AgentConfig(
        cwd=str(workspace),
        auto_confirm=True,
        require_diff_preview=False,
    )
    result = execute_tool(
        ToolCall("read_file", {"path": str(outside_secret)}, "t1"),
        config,
    )
    assert result.is_error
    assert result.outcome == "blocked_by_workspace"
    audit = get_audit_log()
    assert any(e.decision == "deny" for e in audit)


def test_yes_does_not_bypass_bash_external(workspace: Path, outside_secret: Path):
    config = AgentConfig(cwd=str(workspace), auto_confirm=True)
    result = execute_tool(
        ToolCall("bash", {"command": f"type {outside_secret}"}, "t1"),
        config,
    )
    assert result.is_error
    assert result.outcome == "blocked_by_workspace"


def test_fenced_mode_same_workspace_restrictions(workspace: Path, outside_secret: Path):
    calls = resolve_tool_calls(
        f'```read_file\n{outside_secret}\n```',
        [],
        tool_mode="fenced",
    )
    assert len(calls) == 1
    config = AgentConfig(cwd=str(workspace), auto_confirm=True)
    result = execute_tool(calls[0], config)
    assert result.is_error
    assert result.outcome == "blocked_by_workspace"


def test_audit_log_records_deny(workspace: Path, outside_secret: Path):
    execute_tool(
        ToolCall("read_file", {"path": str(outside_secret)}, "t1"),
        AgentConfig(cwd=str(workspace)),
    )
    entries = get_audit_log()
    assert len(entries) >= 1
    assert entries[-1].tool == "read_file"
    assert entries[-1].decision == "deny"


def test_symlink_outside_workspace(workspace: Path, outside_secret: Path):
    link = workspace / "escape_link"
    try:
        link.symlink_to(outside_secret)
    except OSError:
        if os.name == "nt":
            pytest.skip("Windows sin privilegio para symlinks")
        raise
    if not link.exists() and not link.is_symlink():
        pytest.skip("No se pudo crear symlink")
    decision = check_path_allowed(str(workspace), "escape_link")
    # resolve() sigue el symlink; debe detectar salida del workspace o no filtrar
    result = execute_tool(
        ToolCall("read_file", {"path": "escape_link"}, "t1"),
        AgentConfig(cwd=str(workspace)),
    )
    if "outside-secret" in result.content:
        pytest.fail("Symlink permitió leer fuera del workspace")
    assert result.is_error or "outside-secret" not in result.content


def test_run_bash_uses_policy(workspace: Path):
    out = run_bash(str(workspace), "rm -rf /")
    assert out.startswith("Error:")
