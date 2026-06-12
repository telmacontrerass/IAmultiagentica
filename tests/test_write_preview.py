import json
from pathlib import Path
from unittest.mock import patch

from ci2lab.harness import AgentConfig, default_selection, run_agent
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.tools.write_preview import preview_edit_file, preview_write_file
from ci2lab.harness.types import ToolCall


def test_edit_file_rejects_identical_old_and_new_strings(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("hola\n", encoding="utf-8")
    preview = preview_edit_file(str(tmp_path), "a.txt", "hola", "hola")
    assert not preview.is_valid
    assert "son iguales" in (preview.validation_error or "")


def test_edit_file_missing_path_lists_root_py_files(tmp_path):
    (tmp_path / "Pruebas.py").write_text("x\n", encoding="utf-8")
    preview = preview_edit_file(
        str(tmp_path),
        "src/main.py",
        "a",
        "b",
    )
    assert not preview.is_valid
    assert "Pruebas.py" in (preview.validation_error or "")


def test_edit_file_generates_diff(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hello world\n", encoding="utf-8")
    preview = preview_edit_file(str(tmp_path), "a.txt", "world", "ci2lab")
    assert preview.is_valid
    assert not preview.is_new_file
    assert "-world" in preview.diff or "world" in preview.diff
    assert "+ci2lab" in preview.diff or "ci2lab" in preview.diff


def test_write_file_existing_generates_diff(tmp_path):
    path = tmp_path / "b.txt"
    path.write_text("line one\n", encoding="utf-8")
    preview = preview_write_file(str(tmp_path), "b.txt", "line two\n")
    assert preview.is_valid
    assert not preview.is_new_file
    assert "line one" in preview.diff or "line two" in preview.diff


def test_write_file_new_shows_preview(tmp_path):
    preview = preview_write_file(str(tmp_path), "new.txt", "contenido nuevo")
    assert preview.is_valid
    assert preview.is_new_file
    assert "contenido nuevo" in preview.format_for_display()
    assert "crear archivo nuevo" in preview.format_for_display().lower()


def test_write_tools_disabled(tmp_path):
    config = AgentConfig(cwd=str(tmp_path), write_tools_enabled=False)
    call = ToolCall(
        name="write_file",
        arguments={"path": "x.txt", "content": "hola"},
        call_id="w1",
    )
    result = execute_tool(call, config)
    assert result.is_error
    assert result.outcome == "blocked_by_config"
    assert not (tmp_path / "x.txt").exists()


def test_deny_does_not_modify_file(tmp_path):
    (tmp_path / "a.txt").write_text("original", encoding="utf-8")
    config = AgentConfig(
        cwd=str(tmp_path),
        require_diff_preview=True,
        confirm_callback=lambda _n, _s: False,
    )
    call = ToolCall(
        name="edit_file",
        arguments={
            "path": "a.txt",
            "old_string": "original",
            "new_string": "changed",
        },
        call_id="e1",
    )
    with patch("ci2lab.harness.write_permissions._console.print"):
        result = execute_tool(call, config)
    assert result.is_error
    assert result.outcome == "denied"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "original"


def test_approve_modifies_file(tmp_path):
    (tmp_path / "a.txt").write_text("original", encoding="utf-8")
    config = AgentConfig(
        cwd=str(tmp_path),
        require_diff_preview=True,
        confirm_callback=lambda _n, _s: True,
    )
    call = ToolCall(
        name="edit_file",
        arguments={
            "path": "a.txt",
            "old_string": "original",
            "new_string": "changed",
        },
        call_id="e2",
    )
    with patch("ci2lab.harness.write_permissions._console.print"):
        result = execute_tool(call, config)
    assert not result.is_error
    assert result.outcome == "approved"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "changed"


def test_yes_does_not_skip_diff_preview(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    config = AgentConfig(
        cwd=str(tmp_path),
        auto_confirm=True,
        require_diff_preview=True,
        confirm_callback=lambda _n, _s: False,
    )
    call = ToolCall(
        name="write_file",
        arguments={"path": "a.txt", "content": "y"},
        call_id="w2",
    )
    with patch("ci2lab.harness.write_permissions._console.print"):
        result = execute_tool(call, config)
    assert result.outcome == "denied"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "x"


def test_logging_records_write_outcome(tmp_path):
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")
    runs = tmp_path / "runs"
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        run_log_enabled=True,
        runs_dir=str(runs),
        require_diff_preview=True,
        confirm_callback=lambda _n, _s: True,
    )
    selection = default_selection("test:1b")
    with_tool = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {
                "name": "edit_file",
                "arguments": json.dumps({
                    "path": "a.txt",
                    "old_string": "old",
                    "new_string": "new",
                }),
            },
        }],
    )
    final = LLMResponse(content="Hecho.", tool_calls=[])

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
        MockClient.return_value.chat.side_effect = [with_tool, final]
        with patch("ci2lab.harness.write_permissions._console.print"):
            run_agent("edita a.txt", selection, config=config)

    run_dir = next(runs.iterdir())
    line = (run_dir / "tool_calls.jsonl").read_text(encoding="utf-8").strip()
    entry = json.loads(line)
    assert entry["tool"] == "edit_file"
    assert entry["outcome"] == "approved"
