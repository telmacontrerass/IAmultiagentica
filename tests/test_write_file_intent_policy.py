"""Write policy tests: workspace, secrets, and agent intent."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ci2lab.harness import default_selection, run_agent
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.tools.secret_files import POLICY_SECRET_FILE_BLOCKED
from ci2lab.harness.types import AgentConfig, ToolCall

SECRET_PAYLOAD = "TOKEN=SHOULD_NOT_WRITE"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "docs").mkdir()
    return ws


@pytest.fixture
def write_config(workspace: Path) -> AgentConfig:
    return AgentConfig(
        cwd=str(workspace),
        auto_confirm=True,
        require_diff_preview=False,
        write_tools_enabled=True,
        stream=False,
        run_log_enabled=False,
    )


def test_write_file_inside_workspace(write_config: AgentConfig, workspace: Path):
    target = workspace / "docs" / "generated_test.md"
    result = execute_tool(
        ToolCall(
            name="write_file",
            arguments={"path": "docs/generated_test.md", "content": "# OK\n"},
            call_id="w1",
        ),
        write_config,
    )
    assert not result.is_error
    assert target.read_text(encoding="utf-8") == "# OK\n"


def test_write_file_outside_workspace_blocked(write_config: AgentConfig, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    result = execute_tool(
        ToolCall(
            name="write_file",
            arguments={"path": str(outside), "content": "hack"},
            call_id="w2",
        ),
        write_config,
    )
    assert result.is_error
    assert result.outcome == "blocked_by_workspace"
    assert not outside.exists()


def test_write_file_sensitive_path_blocked(write_config: AgentConfig, workspace: Path):
    result = execute_tool(
        ToolCall(
            name="write_file",
            arguments={"path": ".env.test", "content": SECRET_PAYLOAD},
            call_id="w3",
        ),
        write_config,
    )
    assert result.is_error
    assert result.outcome == "blocked_by_secret_policy"
    assert POLICY_SECRET_FILE_BLOCKED in result.content
    assert SECRET_PAYLOAD not in result.content
    assert not (workspace / ".env.test").exists()


def test_write_file_yes_does_not_bypass_workspace(workspace: Path, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    config = AgentConfig(
        cwd=str(workspace),
        auto_confirm=True,
        require_diff_preview=False,
        write_tools_enabled=True,
    )
    result = execute_tool(
        ToolCall(
            name="write_file",
            arguments={"path": "../outside.txt", "content": "x"},
            call_id="w4",
        ),
        config,
    )
    assert result.is_error
    assert result.outcome == "blocked_by_workspace"
    assert not outside.exists()


def test_run_agent_explicit_create_calls_write_file(workspace: Path):
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=str(workspace),
        stream=False,
        auto_confirm=True,
        require_diff_preview=False,
        write_tools_enabled=True,
        run_log_enabled=False,
    )
    write_call = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "docs/hello.md", "content": "# Hello\n"}),
                },
            }
        ],
    )
    final = LLMResponse(content="File docs/hello.md created.", tool_calls=[])

    with patch("ci2lab.console.console.print"):
        with patch("ci2lab.harness.query.loop.LLMClient") as mock_cls:
            client = mock_cls.return_value
            client.chat.side_effect = [write_call, final]
            with patch(
                "ci2lab.harness.query.loop.execute_tool", wraps=execute_tool
            ) as execute_mock:
                run_agent(
                    "Create docs/hello.md with a title Hello",
                    selection,
                    config=config,
                )
            write_calls = [c for c in execute_mock.call_args_list if c[0][0].name == "write_file"]

    assert len(write_calls) == 1
    assert (workspace / "docs" / "hello.md").read_text(encoding="utf-8") == "# Hello\n"


def test_run_agent_blocked_read_without_spontaneous_error_file(workspace: Path, tmp_path: Path):
    outside = tmp_path / "outside" / "secret.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("decoy", encoding="utf-8")

    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=str(workspace),
        stream=False,
        auto_confirm=True,
        require_diff_preview=False,
        write_tools_enabled=True,
        run_log_enabled=False,
        max_rounds=4,
    )
    read_call = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "read_file",
                    "arguments": json.dumps({"path": str(outside)}),
                },
            }
        ],
    )
    final = LLMResponse(
        content="I can't read files outside the workspace.",
        tool_calls=[],
    )

    with patch("ci2lab.console.console.print"):
        with patch("ci2lab.harness.query.loop.LLMClient") as mock_cls:
            client = mock_cls.return_value
            client.chat.side_effect = [read_call, final]
            with patch(
                "ci2lab.harness.query.loop.execute_tool", wraps=execute_tool
            ) as execute_mock:
                run_agent("Read the external secret", selection, config=config)
            write_calls = [c for c in execute_mock.call_args_list if c[0][0].name == "write_file"]

    assert len(write_calls) == 0
    assert not (workspace / "ci2lab_error.txt").exists()


def test_system_prompt_allows_explicit_write_and_discourages_error_files():
    from ci2lab.harness import default_selection
    from ci2lab.harness.prompts import build_system_prompt

    text = build_system_prompt(default_selection("test:1b"), ".")
    assert "write_file" in text
    assert "diagnostic or log files" in text.lower()
    assert "explicit" in text.lower()


def test_write_tool_schemas_hidden_when_writes_disabled(workspace: Path):
    # The schemas offered to the model must agree with what the executor will
    # actually run: a disabled write tool is not offered at all, instead of
    # being advertised and then blocked (a guaranteed wasted round).
    from ci2lab.harness.security.write_permissions import WRITE_TOOLS
    from ci2lab.harness.tools.registry import get_function_schemas

    disabled = AgentConfig(cwd=str(workspace), write_tools_enabled=False)
    names = {schema["function"]["name"] for schema in get_function_schemas(disabled)}
    assert not (names & WRITE_TOOLS)
    assert {"read_file", "grep", "ls", "bash"} <= names

    enabled = AgentConfig(cwd=str(workspace), write_tools_enabled=True)
    names_enabled = {schema["function"]["name"] for schema in get_function_schemas(enabled)}
    assert names_enabled >= WRITE_TOOLS


def test_system_prompt_declares_read_only_session(workspace: Path):
    from ci2lab.harness import default_selection
    from ci2lab.harness.prompts import build_system_prompt

    selection = default_selection("test:1b")
    read_only = build_system_prompt(
        selection,
        str(workspace),
        config=AgentConfig(cwd=str(workspace), write_tools_enabled=False),
    )
    assert "Read-only session" in read_only

    writable = build_system_prompt(
        selection,
        str(workspace),
        config=AgentConfig(cwd=str(workspace)),
    )
    assert "Read-only session" not in writable
