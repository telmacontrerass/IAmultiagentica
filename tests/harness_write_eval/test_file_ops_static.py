"""P2.10 static harness write eval — deterministic, sin LLM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci2lab.evals.harness_write_eval import (
    compute_workspace_diff,
    oracle_add_function,
    oracle_create_file_simple,
    oracle_edit_json,
    oracle_modify_exact_line,
    oracle_outside_workspace_block,
    run_case_oracle,
    snapshot_workspace,
    static_write_config,
)
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.tools.write_preview import preview_edit_file, preview_write_file
from ci2lab.harness.types import ToolCall


def _cfg(tmp_path: Path):
    return static_write_config(tmp_path)


def _write(call_id: str, path: str, content: str, tmp_path: Path):
    return execute_tool(
        ToolCall(
            name="write_file",
            arguments={"path": path, "content": content},
            call_id=call_id,
        ),
        _cfg(tmp_path),
    )


def _edit(
    call_id: str,
    path: str,
    old: str,
    new: str,
    tmp_path: Path,
    *,
    replace_all: bool = False,
):
    return execute_tool(
        ToolCall(
            name="edit_file",
            arguments={
                "path": path,
                "old_string": old,
                "new_string": new,
                "replace_all": replace_all,
            },
            call_id=call_id,
        ),
        _cfg(tmp_path),
    )


def test_static_create_new_file(tmp_path: Path):
    result = _write("w1", "hello.txt", "hola", tmp_path)
    assert not result.is_error
    ok, detail = oracle_create_file_simple(tmp_path)
    assert ok, detail


def test_static_modify_exact_line(tmp_path: Path):
    (tmp_path / "version.py").write_text('VERSION = "0.1.0"\n', encoding="utf-8")
    result = _edit(
        "e1",
        "version.py",
        'VERSION = "0.1.0"',
        'VERSION = "0.1.1"',
        tmp_path,
    )
    assert not result.is_error
    ok, detail = oracle_modify_exact_line(tmp_path)
    assert ok, detail


def test_static_create_nested_file(tmp_path: Path):
    result = _write("w2", "pkg/module.txt", "nested", tmp_path)
    assert not result.is_error
    target = tmp_path / "pkg" / "module.txt"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "nested"


def test_static_edit_json_valid(tmp_path: Path):
    original = {"enabled": False, "threshold": 3}
    (tmp_path / "config.json").write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
    result = _edit(
        "e2",
        "config.json",
        '"enabled": false',
        '"enabled": true',
        tmp_path,
    )
    assert not result.is_error
    ok, detail = oracle_edit_json(tmp_path)
    assert ok, detail


def test_static_block_outside_workspace(tmp_path: Path):
    outside = tmp_path.parent / "harness_write_outside"
    outside.mkdir(exist_ok=True)
    result = _write("w3", "../outside.txt", "should_not_exist", tmp_path)
    assert result.is_error
    assert (
        result.outcome
        in {
            "blocked_by_workspace",
            "blocked",
            "denied",
            None,
        }
        or "workspace" in (result.content or "").lower()
    )
    ok, detail = oracle_outside_workspace_block(tmp_path, outside)
    assert ok, detail


def test_static_preserves_utf8(tmp_path: Path):
    content = "cafe \u00f1o \u2603 unicode"
    result = _write("w4", "utf8.txt", content, tmp_path)
    assert not result.is_error
    saved = (tmp_path / "utf8.txt").read_text(encoding="utf-8")
    assert saved == content


def test_static_diff_evidence_on_edit(tmp_path: Path):
    (tmp_path / "note.txt").write_text("alpha\n", encoding="utf-8")
    before = snapshot_workspace(tmp_path)
    preview = preview_edit_file(str(tmp_path), "note.txt", "alpha", "beta")
    assert preview.is_valid
    assert preview.diff
    assert "alpha" in preview.diff or "beta" in preview.diff
    result = _edit("e3", "note.txt", "alpha", "beta", tmp_path)
    assert not result.is_error
    after = snapshot_workspace(tmp_path)
    diff = compute_workspace_diff(before, after)
    assert "beta" in diff


def test_static_add_function_oracle(tmp_path: Path):
    source = "def add(a, b):\n    return a + b\n"
    (tmp_path / "math_utils.py").write_text(source, encoding="utf-8")
    ok, detail = oracle_add_function(tmp_path)
    assert ok, detail


def test_static_write_preview_new_file(tmp_path: Path):
    preview = preview_write_file(str(tmp_path), "new.txt", "hola")
    assert preview.is_valid
    assert preview.is_new_file
    display = preview.format_for_display()
    assert "hola" in display


@pytest.mark.parametrize(
    "case_id,setup,oracle_fn",
    [
        (
            "create_file_simple",
            lambda p: _write("w5", "hello.txt", "hola", p),
            oracle_create_file_simple,
        ),
        (
            "modify_exact_line",
            lambda p: (
                (p / "version.py").write_text('VERSION = "0.1.0"\n', encoding="utf-8"),
                _edit(
                    "e4",
                    "version.py",
                    'VERSION = "0.1.0"',
                    'VERSION = "0.1.1"',
                    p,
                ),
            ),
            oracle_modify_exact_line,
        ),
    ],
)
def test_run_case_oracle_dispatch(case_id, setup, oracle_fn, tmp_path: Path):
    setup(tmp_path)
    ok, detail = run_case_oracle(case_id, tmp_path)
    assert ok, detail
    ok2, _ = oracle_fn(tmp_path)
    assert ok2
