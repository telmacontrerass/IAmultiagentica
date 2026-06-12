"""Tests for MCP client integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ci2lab.harness.mcp.config import load_mcp_config
from ci2lab.harness.mcp.session import close_mcp_manager, get_mcp_manager, mcp_tool_id
from ci2lab.harness.tools.registry import execute_tool, get_function_schemas
from ci2lab.harness.types import AgentConfig, ToolCall

_MOCK_SERVER = Path(__file__).parent / "fixtures" / "mock_mcp_server.py"


@pytest.fixture
def workspace_with_mcp(tmp_path: Path) -> Path:
    cfg_dir = tmp_path / ".ci2lab"
    cfg_dir.mkdir()
    cfg_dir.joinpath("mcp.json").write_text(
        json.dumps({
            "mcpServers": {
                "mock": {
                    "command": sys.executable,
                    "args": [str(_MOCK_SERVER)],
                }
            }
        }),
        encoding="utf-8",
    )
    return tmp_path


def test_load_mcp_config(workspace_with_mcp: Path) -> None:
    configs = load_mcp_config(str(workspace_with_mcp))
    assert len(configs) == 1
    assert configs[0].name == "mock"
    assert configs[0].command == sys.executable


def test_mcp_connect_and_call(workspace_with_mcp: Path) -> None:
    close_mcp_manager(str(workspace_with_mcp))
    mgr = get_mcp_manager(str(workspace_with_mcp), connect=True)
    try:
        assert mgr.tools
        tool_id = mcp_tool_id("mock", "echo")
        output = mgr.call_by_id(tool_id, {"text": "hi"})
        assert output == "echo:hi"
    finally:
        close_mcp_manager(str(workspace_with_mcp))


def test_mcp_schemas_and_execute(workspace_with_mcp: Path) -> None:
    close_mcp_manager(str(workspace_with_mcp))
    cfg = AgentConfig(cwd=str(workspace_with_mcp))
    try:
        schemas = get_function_schemas(cfg)
        tool_id = mcp_tool_id("mock", "echo")
        names = {s["function"]["name"] for s in schemas}
        assert tool_id in names

        result = execute_tool(
            ToolCall(name=tool_id, arguments={"text": "ping"}),
            cfg,
        )
        assert not result.is_error
        assert result.content == "echo:ping"
    finally:
        close_mcp_manager(str(workspace_with_mcp))
