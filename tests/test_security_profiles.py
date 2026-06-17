"""Tests de perfiles de seguridad y seccion security en ci2lab.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci2lab.config import Ci2LabConfig, load_config
from ci2lab.harness.security_profiles import (
    DEFAULT_PROFILE,
    UnknownSecurityProfileError,
    parse_security_config,
)
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.tools.secret_files import POLICY_SECRET_FILE_BLOCKED
from ci2lab.harness.types import AgentConfig, ToolCall


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "safe.txt").write_text("hello\n", encoding="utf-8")
    (ws / ".env").write_text("SECRET=leak\n", encoding="utf-8")
    return ws


def _agent(workspace: Path, profile: str = "standard", **kwargs) -> AgentConfig:
    return AgentConfig(cwd=str(workspace), security_profile=profile, **kwargs)


def _run(workspace: Path, tool: str, args: dict, profile: str = "standard", **cfg):
    config = _agent(workspace, profile=profile, **cfg)
    return execute_tool(
        ToolCall(name=tool, arguments=args, call_id="t1"),
        config,
    )


def test_default_profile_is_standard():
    cfg = parse_security_config(None)
    assert cfg.profile == DEFAULT_PROFILE
    assert DEFAULT_PROFILE == "standard"


def test_unknown_profile_raises():
    with pytest.raises(UnknownSecurityProfileError, match="Unknown"):
        parse_security_config({"profile": "paranoid"})


def test_load_config_unknown_profile_fails(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci2lab.json").write_text(
        json.dumps({"security": {"profile": "invalid"}}),
        encoding="utf-8",
    )
    with pytest.raises(UnknownSecurityProfileError):
        load_config()


def test_strict_blocks_write_file(workspace: Path):
    result = _run(workspace, "write_file", {"path": "out.txt", "content": "x"}, "strict")
    assert result.is_error
    assert result.outcome == "blocked_by_security_profile"
    assert "TOOL_BLOCKED_BY_SECURITY_PROFILE" in result.content
    assert "write_file" in result.content
    assert "strict" in result.content


def test_strict_blocks_edit_file(workspace: Path):
    (workspace / "out.txt").write_text("old\n", encoding="utf-8")
    result = _run(
        workspace,
        "edit_file",
        {"path": "out.txt", "old_string": "old", "new_string": "new"},
        "strict",
    )
    assert result.is_error
    assert result.outcome == "blocked_by_security_profile"


def test_strict_blocks_bash(workspace: Path):
    result = _run(workspace, "bash", {"command": "echo hi"}, "strict")
    assert result.is_error
    assert result.outcome == "blocked_by_security_profile"


def test_strict_allows_read_file(workspace: Path):
    result = _run(workspace, "read_file", {"path": "safe.txt"}, "strict")
    assert not result.is_error
    assert "hello" in result.content


def test_strict_still_blocks_secrets(workspace: Path):
    result = _run(workspace, "read_file", {"path": ".env"}, "strict")
    assert result.is_error
    assert result.outcome == "blocked_by_secret_policy"
    assert POLICY_SECRET_FILE_BLOCKED in result.content


def test_standard_allows_write_file(workspace: Path):
    result = _run(
        workspace,
        "write_file",
        {"path": "out.txt", "content": "ok"},
        "standard",
        auto_confirm=True,
        require_diff_preview=False,
    )
    assert not result.is_error
    assert (workspace / "out.txt").read_text(encoding="utf-8") == "ok"


def test_standard_blocks_external_write(workspace: Path):
    result = _run(
        workspace,
        "write_file",
        {"path": "../outside.txt", "content": "x"},
        "standard",
        auto_confirm=True,
        require_diff_preview=False,
    )
    assert result.is_error
    assert result.outcome == "blocked_by_workspace"


def test_dev_blocks_secrets(workspace: Path):
    result = _run(workspace, "read_file", {"path": ".env"}, "dev")
    assert result.is_error
    assert result.outcome == "blocked_by_secret_policy"


def test_audit_blocks_write_file(workspace: Path):
    result = _run(
        workspace,
        "write_file",
        {"path": "out.txt", "content": "x"},
        "audit",
    )
    assert result.is_error
    assert result.outcome == "blocked_by_security_profile"


def test_yes_does_not_bypass_strict(workspace: Path):
    result = _run(
        workspace,
        "bash",
        {"command": "echo hi"},
        "strict",
        auto_confirm=True,
    )
    assert result.is_error
    assert result.outcome == "blocked_by_security_profile"


def test_security_limits_map_to_agent_config(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci2lab.json").write_text(
        json.dumps({
            "security": {
                "profile": "standard",
                "limits": {
                    "bash_timeout_seconds": 45,
                    "max_tool_output_chars": 5000,
                },
            }
        }),
        encoding="utf-8",
    )
    runtime = load_config()
    limits = runtime.security.resolved_limits()
    assert limits.bash_timeout_seconds == 45
    assert limits.max_tool_output_chars == 5000

    agent = AgentConfig(
        cwd=str(tmp_path),
        security_profile=runtime.security.profile,
        bash_timeout_seconds=limits.bash_timeout_seconds,
        max_tool_output_chars=limits.max_tool_output_chars,
    )
    assert agent.bash_timeout_seconds == 45
    assert agent.max_tool_output_chars == 5000


def test_dev_profile_default_limits_are_higher():
    cfg = parse_security_config({"profile": "dev"})
    limits = cfg.resolved_limits()
    assert limits.bash_timeout_seconds == 120
    assert limits.max_tool_output_chars == 20_000


def test_cli_without_security_section_uses_standard(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci2lab.json").write_text('{"model": "test:1b"}', encoding="utf-8")
    runtime = load_config()
    assert runtime.security.profile == "standard"
