"""Tests de confinamiento al workspace y anti-bypass."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ci2lab.harness import default_selection, run_agent
from ci2lab.harness.llm_client import LLMResponse

from ci2lab.harness.policy import (
    POLICY_REPEAT_MESSAGE,
    is_policy_error,
    tool_call_signature,
)
from ci2lab.harness.tools.bash import run_bash
from ci2lab.harness.tools.bash_safety import check_bash_blocked
from ci2lab.harness.tools.filesystem import read_file
from ci2lab.harness.tools.paths import PathViolationError, resolve_path
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "inside.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("decoy-content", encoding="utf-8")
    return ws


@pytest.fixture
def outside_secret(tmp_path: Path) -> Path:
    return (tmp_path / "outside" / "secret.txt").resolve()


def test_read_file_absolute_outside_blocked(workspace: Path, outside_secret: Path):
    out = read_file(str(workspace), str(outside_secret))
    assert "fuera del workspace" in out


def test_read_file_dotdot_outside_blocked(workspace: Path):
    out = read_file(str(workspace), "../outside/secret.txt")
    assert "fuera del workspace" in out


def test_resolve_path_blocks_traversal(workspace: Path):
    with pytest.raises(PathViolationError, match="fuera del workspace"):
        resolve_path("../outside/secret.txt", str(workspace))


def test_all_file_tools_use_resolve_path():
    from ci2lab.harness.tools import filesystem as fs

    for name in ("read_file", "ls", "glob_search", "grep_search", "write_file", "edit_file"):
        assert hasattr(fs, name)


@pytest.mark.parametrize(
    "command",
    [
        "type {outside}",
        "copy {outside} .",
        "Get-Content {outside}",
        "cat {outside}",
        "cp {outside} inside.txt",
    ],
)
def test_bash_external_paths_blocked_before_run(
    workspace: Path, outside_secret: Path, command: str
):
    cmd = command.format(outside=outside_secret)
    blocked = check_bash_blocked(cmd, cwd=str(workspace))
    assert blocked is not None
    assert "fuera del workspace" in blocked.lower()


def test_bash_normal_inside_workspace_allowed(workspace: Path):
    blocked = check_bash_blocked("dir inside.txt", cwd=str(workspace))
    assert blocked is None


def test_run_bash_inside_workspace_executes(workspace: Path):
    with patch("ci2lab.harness.tools.bash.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""
        out = run_bash(str(workspace), "echo ok")
    assert "ok" in out
    run.assert_called_once()


def test_execute_tool_bash_blocked_without_confirmation(
    workspace: Path, outside_secret: Path
):
    config = AgentConfig(cwd=str(workspace), auto_confirm=True)
    call = ToolCall(
        name="bash",
        arguments={"command": f"type {outside_secret}"},
        call_id="c1",
    )
    with patch("ci2lab.harness.permissions.check_permission") as perm:
        result = execute_tool(call, config)
    perm.assert_not_called()
    assert result.is_error
    assert result.outcome == "blocked_by_workspace"
    assert "fuera del workspace" in result.content.lower()


def test_execute_tool_read_file_outside_has_workspace_outcome(
    workspace: Path, outside_secret: Path
):
    config = AgentConfig(cwd=str(workspace))
    call = ToolCall(
        name="read_file",
        arguments={"path": str(outside_secret)},
        call_id="c1",
    )
    result = execute_tool(call, config)
    assert result.is_error
    assert result.outcome == "blocked_by_workspace"


def test_policy_repeat_blocks_same_call(workspace: Path, outside_secret: Path):
    config = AgentConfig(cwd=str(workspace))
    call = ToolCall(
        name="read_file",
        arguments={"path": str(outside_secret)},
        call_id="c1",
    )
    first = execute_tool(call, config)
    assert is_policy_error(first)

    sig = tool_call_signature(call)
    blocked_sigs = {sig}
    assert sig in blocked_sigs
    repeat = ToolResult(
        tool_name=call.name,
        content=POLICY_REPEAT_MESSAGE,
        is_error=True,
        call_id=call.call_id,
        outcome="blocked_by_policy",
    )
    assert repeat.outcome == "blocked_by_policy"
    assert "No repitas" in repeat.content


def test_bash_traversal_copy_blocked(workspace: Path, tmp_path: Path):
    outside = tmp_path / "outside" / "secret.txt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("decoy", encoding="utf-8")
    cmd = "cp ../outside/secret.txt ."
    blocked = check_bash_blocked(cmd, cwd=str(workspace))
    assert blocked is not None


def test_run_agent_does_not_repeat_blocked_read_file(tmp_path: Path, outside_secret: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=str(ws),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        max_rounds=5,
    )
    outside_arg = json.dumps({"path": str(outside_secret)})
    read_call = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {"name": "read_file", "arguments": outside_arg},
            }
        ],
    )
    final = LLMResponse(
        content="No puedo leer archivos fuera del workspace.",
        tool_calls=[],
    )

    with patch("ci2lab.harness.loop.LLMClient") as mock_client_cls:
        client = mock_client_cls.return_value
        client.chat.side_effect = [read_call, read_call, final]
        with patch(
            "ci2lab.harness.loop.execute_tool", wraps=execute_tool
        ) as execute_mock:
            result = run_agent("lee el secreto externo", selection, config=config)

    assert execute_mock.call_count == 1
    assert "workspace" in result.lower()
