"""Tests for workspace hook lifecycle."""

from __future__ import annotations

import json
from types import SimpleNamespace

from ci2lab.harness.hooks import emit_hook_event
from ci2lab.harness.types import AgentConfig


def test_emit_hook_event_runs_configured_command(tmp_path, monkeypatch):
    hooks_dir = tmp_path / ".ci2lab"
    hooks_dir.mkdir()
    hooks_dir.joinpath("hooks.json").write_text(
        json.dumps({"before_tool": [{"command": "ci2lab-hook"}]}),
        encoding="utf-8",
    )
    calls = []

    def fake_run(*args, **kwargs):
        kwargs["args"] = args[0]
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("ci2lab.harness.hooks.subprocess.run", fake_run)

    warnings = emit_hook_event(
        AgentConfig(cwd=str(tmp_path)),
        "before_tool",
        {"tool": "read_file", "arguments": {"path": "x.py"}, "round": 1},
    )

    assert warnings == []
    assert calls[0]["args"] == "ci2lab-hook"
    assert calls[0]["cwd"] == str(tmp_path)
    assert calls[0]["shell"] is True
    assert calls[0]["env"]["CI2LAB_HOOK_EVENT"] == "before_tool"
    payload = json.loads(calls[0]["input"])
    assert payload["tool"] == "read_file"


def test_emit_hook_event_reports_hook_failures(tmp_path, monkeypatch):
    hooks_dir = tmp_path / ".ci2lab"
    hooks_dir.mkdir()
    hooks_dir.joinpath("hooks.json").write_text(
        json.dumps({"after_final_answer": ["bad-hook"]}),
        encoding="utf-8",
    )

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=2, stdout="", stderr="boom")

    monkeypatch.setattr("ci2lab.harness.hooks.subprocess.run", fake_run)

    warnings = emit_hook_event(
        AgentConfig(cwd=str(tmp_path)),
        "after_final_answer",
        {"answer": "done"},
    )

    assert "bad-hook" in warnings[0]
    assert "boom" in warnings[0]
