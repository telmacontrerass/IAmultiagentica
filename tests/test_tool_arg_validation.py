"""Tests for tool argument validation: a missing required arg → a clear error."""

from __future__ import annotations

from pathlib import Path

from ci2lab.harness.tools.executor_parts.arguments import validate_tool_arguments
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall

# --- validate_tool_arguments (pure function) ---


def test_missing_required_argument_is_reported() -> None:
    error = validate_tool_arguments("write_file", {"path": "notes.txt"})
    assert error is not None
    assert "write_file" in error
    assert "content" in error


def test_all_required_present_passes() -> None:
    assert validate_tool_arguments("write_file", {"path": "a", "content": "b"}) is None


def test_empty_string_counts_as_present() -> None:
    # Presence-only: writing an intentional empty file (content="") must not be
    # rejected, so we check the key exists, never its value.
    assert validate_tool_arguments("write_file", {"path": "a", "content": ""}) is None


def test_mcp_tool_is_not_validated_here() -> None:
    # An mcp__* tool carries its schema on the server, not in FUNCTION_SCHEMAS.
    assert validate_tool_arguments("mcp__server__do", {"anything": 1}) is None


def test_multiple_missing_args_are_all_listed() -> None:
    error = validate_tool_arguments("edit_file", {"path": "a"})
    assert error is not None
    assert "old_string" in error
    assert "new_string" in error


def test_write_pptx_title_is_relaxed_but_slides_required() -> None:
    # title defaults in the handler, so it is no longer required; slides is not.
    assert validate_tool_arguments("write_pptx", {"output_path": "d.pptx", "slides": []}) is None
    error = validate_tool_arguments("write_pptx", {"output_path": "d.pptx"})
    assert error is not None
    assert "slides" in error


# --- execute_tool wiring ---


def test_execute_tool_rejects_missing_argument(tmp_path: Path) -> None:
    config = AgentConfig(cwd=str(tmp_path))
    result = execute_tool(ToolCall(name="write_file", arguments={"path": "x.txt"}), config)

    assert result.is_error
    assert result.outcome == "invalid_arguments"
    assert "content" in result.content
    # Validation returns before the write handler runs, so nothing is written.
    assert not (tmp_path / "x.txt").exists()
