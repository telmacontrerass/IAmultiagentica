import os
import tempfile

from ci2lab.harness.tools.filesystem import read_file, write_file, edit_file, ls
from ci2lab.harness.tools.paths import PathViolationError, resolve_path
from ci2lab.harness.tools.registry import execute_tool, normalize_tool_arguments
from ci2lab.harness.types import AgentConfig, ToolCall


def test_resolve_path_blocks_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            resolve_path("..", tmp)
            assert False, "debería fallar"
        except PathViolationError:
            pass


def test_read_file_null_offset_limit(tmp_path):
    (tmp_path / "config.txt").write_text("version=1.0\n", encoding="utf-8")
    text = read_file(str(tmp_path), "config.txt", offset=None, limit=None)
    assert "version" in text


def test_execute_read_file_strips_null_optional_args(tmp_path):
    (tmp_path / "config.txt").write_text("version=1.0\n", encoding="utf-8")
    call = ToolCall(
        name="read_file",
        arguments={"path": "config.txt", "offset": None, "limit": None},
        call_id="r1",
    )
    result = execute_tool(call, AgentConfig(cwd=str(tmp_path)))
    assert not result.is_error
    assert "version" in result.content


def test_normalize_tool_arguments_drops_nulls():
    assert normalize_tool_arguments({"path": "a", "offset": None}) == {"path": "a"}


def test_read_write_edit_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        write_file(tmp, "a.txt", "hello world")
        assert "hello" in read_file(tmp, "a.txt")
        edit_file(tmp, "a.txt", "world", "ci2lab")
        assert "ci2lab" in read_file(tmp, "a.txt")
        listing = ls(tmp, ".")
        assert "a.txt" in listing
