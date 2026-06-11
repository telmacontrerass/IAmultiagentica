"""Tests de politica de archivos sensibles en read_file y grep."""

from __future__ import annotations

from pathlib import Path

import pytest

from ci2lab.harness.tools.filesystem import grep_search, read_file
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.tools.secret_files import POLICY_SECRET_FILE_BLOCKED
from ci2lab.harness.types import AgentConfig, ToolCall

LEAK_MARKERS = (
    "SHOULD_NOT_LEAK",
    "PRIVATE_KEY_SHOULD_NOT_LEAK",
    "CREDENTIAL_SHOULD_NOT_LEAK",
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".env.test").write_text("FAKE_TOKEN=SHOULD_NOT_LEAK\n", encoding="utf-8")
    (ws / "private.pem").write_text("PRIVATE_KEY_SHOULD_NOT_LEAK\n", encoding="utf-8")
    creds = ws / "config"
    creds.mkdir()
    (creds / "credentials.json").write_text(
        '{"api": "CREDENTIAL_SHOULD_NOT_LEAK"}', encoding="utf-8"
    )
    (ws / "safe.txt").write_text("visible content\n", encoding="utf-8")
    return ws


def _assert_no_leak(text: str) -> None:
    for marker in LEAK_MARKERS:
        assert marker not in text


@pytest.mark.parametrize(
    "path",
    [".env.test", "private.pem", "config/credentials.json"],
)
def test_read_file_blocks_sensitive_paths(workspace: Path, path: str):
    out = read_file(str(workspace), path)
    assert POLICY_SECRET_FILE_BLOCKED in out
    _assert_no_leak(out)


def test_execute_tool_read_file_secret_outcome(workspace: Path):
    config = AgentConfig(cwd=str(workspace))
    call = ToolCall(name="read_file", arguments={"path": ".env.test"}, call_id="c1")
    result = execute_tool(call, config)
    assert result.is_error
    assert result.outcome == "blocked_by_secret_policy"
    _assert_no_leak(result.content)


def test_grep_skips_sensitive_files_without_leaking(workspace: Path):
    out = grep_search(str(workspace), "SHOULD_NOT_LEAK", ".")
    assert "FAKE_TOKEN=SHOULD_NOT_LEAK" not in out
    assert "PRIVATE_KEY_SHOULD_NOT_LEAK" not in out
    assert "CREDENTIAL_SHOULD_NOT_LEAK" not in out
    assert "omitieron" in out.lower() or "Sin coincidencias" in out


def test_grep_blocks_when_target_is_sensitive_file(workspace: Path):
    out = grep_search(str(workspace), "SHOULD_NOT_LEAK", ".env.test")
    assert POLICY_SECRET_FILE_BLOCKED in out
    _assert_no_leak(out)


def test_grep_still_finds_safe_files(workspace: Path):
    out = grep_search(str(workspace), "visible", ".")
    assert "safe.txt" in out
    assert "visible" in out
