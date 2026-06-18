"""Tests for inspection tools: file_info, tree, inspect_file."""

from __future__ import annotations

from pathlib import Path

import pytest

from ci2lab.harness.tools.inspection import file_info, inspect_file, tree
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.tools.secret_files import POLICY_SECRET_FILE_BLOCKED
from ci2lab.harness.types import AgentConfig, ToolCall

LEAK = "SECRET_SHOULD_NOT_LEAK"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "hello.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (ws / "subdir").mkdir()
    (ws / "subdir" / "nested.txt").write_text("nested\n", encoding="utf-8")
    (ws / ".env.test").write_text(f"TOKEN={LEAK}\n", encoding="utf-8")
    (ws / "private.pem").write_bytes(b"-----BEGIN KEY-----\n")
    (ws / "__pycache__").mkdir()
    (ws / "__pycache__" / "junk.pyc").write_bytes(b"\x00\x01")
    return ws


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "secret.txt").write_text("outside", encoding="utf-8")
    return ext / "secret.txt"


def test_file_info_normal_file(workspace: Path):
    out = file_info(str(workspace), "hello.txt")
    assert "exists: yes" in out
    assert "type: file" in out
    assert "sensitive: no" in out
    assert "approx_lines: 3" in out
    assert LEAK not in out


def test_file_info_directory(workspace: Path):
    out = file_info(str(workspace), "subdir")
    assert "type: dir" in out
    assert "sensitive: no" in out


def test_file_info_sensitive_without_content(workspace: Path):
    out = file_info(str(workspace), ".env.test")
    assert "sensitive: yes" in out
    assert "exists: yes" in out
    assert LEAK not in out
    assert "approx_lines" not in out


def test_file_info_outside_blocked(workspace: Path, outside: Path):
    out = file_info(str(workspace), str(outside))
    assert "outside the workspace" in out


def test_file_info_missing_path(workspace: Path):
    out = file_info(str(workspace), "missing.txt")
    assert "exists: no" in out
    assert "in_workspace: yes" in out


def test_tree_respects_depth_and_skips(workspace: Path):
    out = tree(str(workspace), ".", depth=1, max_entries=50)
    assert "hello.txt" in out
    assert "subdir/" in out
    assert "nested.txt" not in out
    assert "__pycache__" not in out
    assert LEAK not in out


def test_tree_omits_sensitive_entries(workspace: Path):
    out = tree(str(workspace), ".", depth=2, max_entries=50)
    assert "[sensitive omitted]" in out
    assert ".env.test" in out or "private.pem" in out
    assert LEAK not in out


def test_tree_truncates_max_entries(workspace: Path):
    for i in range(10):
        (workspace / f"file_{i}.txt").write_text("x", encoding="utf-8")
    out = tree(str(workspace), ".", depth=1, max_entries=3)
    assert "truncated" in out.lower()


def test_tree_outside_blocked(workspace: Path, outside: Path):
    out = tree(str(workspace), str(outside.parent))
    assert "outside the workspace" in out


def test_inspect_file_range(workspace: Path):
    out = inspect_file(str(workspace), "hello.txt", start=2, end=2)
    assert "2|line2" in out
    assert "line1" not in out.splitlines()[0]


def test_inspect_file_truncated_by_max_lines(workspace: Path):
    lines = "\n".join(f"line{i}" for i in range(1, 201))
    (workspace / "big.txt").write_text(lines + "\n", encoding="utf-8")
    out = inspect_file(str(workspace), "big.txt", start=1, max_lines=10)
    assert "    10|line10" in out
    assert "line11" not in out
    assert "more lines" in out


def test_inspect_file_sensitive_blocked(workspace: Path):
    out = inspect_file(str(workspace), ".env.test")
    assert POLICY_SECRET_FILE_BLOCKED in out
    assert LEAK not in out


def test_inspect_file_outside_blocked(workspace: Path, outside: Path):
    out = inspect_file(str(workspace), str(outside))
    assert "outside the workspace" in out


def test_inspect_file_missing(workspace: Path):
    out = inspect_file(str(workspace), "nope.txt")
    assert "does not exist" in out


def test_inspect_file_binary(workspace: Path):
    (workspace / "data.bin").write_bytes(b"\x00\x01\x02")
    out = inspect_file(str(workspace), "data.bin")
    assert "binary" in out.lower()


def test_execute_tool_inspect_file_secret_outcome(workspace: Path):
    result = execute_tool(
        ToolCall(name="inspect_file", arguments={"path": ".env.test"}, call_id="c1"),
        AgentConfig(cwd=str(workspace)),
    )
    assert result.is_error
    assert result.outcome == "blocked_by_secret_policy"
