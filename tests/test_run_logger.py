import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ci2lab.harness import AgentConfig, default_selection, run_agent
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.run_logger import RunLogger, build_config_snapshot
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import ToolCall


def _agent_config(tmp_path: Path, *, run_log_enabled: bool = True) -> AgentConfig:
    selection = default_selection("test:1b")
    cwd = str(tmp_path)
    agent = AgentConfig(
        cwd=cwd,
        stream=False,
        auto_confirm=True,
        run_log_enabled=run_log_enabled,
        runs_dir=str(tmp_path / "runs"),
        config_snapshot=build_config_snapshot(
            runtime_fields={"model": "test:1b", "workspace": cwd},
            agent_config=AgentConfig(cwd=cwd, runs_dir=str(tmp_path / "runs")),
            selection=selection,
        ),
    )
    return agent


def test_run_logger_creates_run_folder(tmp_path):
    runs = tmp_path / "runs"
    selection = default_selection("test:1b")
    logger = RunLogger(
        runs_dir=runs,
        selection=selection,
        agent_config=AgentConfig(cwd=str(tmp_path), runs_dir=str(runs)),
        config_snapshot={"model": "test:1b"},
        user_prompt="hola",
    )
    run_dir = logger.start()
    assert run_dir is not None
    assert run_dir.is_dir()
    assert (run_dir / "config_snapshot.json").is_file()


def test_run_summary_written_on_finalize(tmp_path):
    runs = tmp_path / "runs"
    selection = default_selection("test:1b")
    agent = AgentConfig(cwd=str(tmp_path), runs_dir=str(runs))
    logger = RunLogger(
        runs_dir=runs,
        selection=selection,
        agent_config=agent,
        config_snapshot={"model": "test:1b"},
        user_prompt="lista archivos",
    )
    run_dir = logger.start()
    logger.set_rounds_completed(2)
    logger.finalize(
        status="success",
        final_answer="Listo.",
        conversation=[{"role": "user", "content": "lista"}],
    )
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "success"
    assert summary["model"] == "test:1b"
    assert summary["workspace"] == str(tmp_path)
    assert summary["rounds"] == 2
    assert (run_dir / "final_answer.md").read_text(encoding="utf-8") == "Listo."


def test_tool_call_logged_to_jsonl(tmp_path):
    runs = tmp_path / "runs"
    selection = default_selection("test:1b")
    agent = AgentConfig(cwd=str(tmp_path), runs_dir=str(runs), auto_confirm=True)
    logger = RunLogger(
        runs_dir=runs,
        selection=selection,
        agent_config=agent,
        config_snapshot={},
        user_prompt="x",
    )
    run_dir = logger.start()
    from datetime import datetime, timezone

    call = ToolCall(name="ls", arguments={"path": "."}, call_id="c1")
    result = execute_tool(call, agent)
    now = datetime.now(timezone.utc)
    logger.record_tool_call(
        round_num=1,
        call=call,
        result=result,
        started_at=now,
        ended_at=now,
    )
    lines = (run_dir / "tool_calls.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool"] == "ls"
    assert entry["round"] == 1


def test_run_agent_writes_run_artifacts(tmp_path):
    selection = default_selection("test:1b")
    config = _agent_config(tmp_path)

    with_tool = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "ls", "arguments": '{"path": "."}'},
        }],
    )
    final = LLMResponse(content="Hay archivos.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        run_agent("lista archivos", selection, config=config)

    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    run_dir = runs[0]
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["tool_call_count"] == 1
    assert "ls" in summary["tools_used"]
    assert (run_dir / "tool_calls.jsonl").is_file()


def test_no_log_skips_run_folder(tmp_path):
    selection = default_selection("test:1b")
    config = _agent_config(tmp_path, run_log_enabled=False)
    mock_response = LLMResponse(content="ok", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = mock_response
        run_agent("hola", selection, config=config)

    assert not (tmp_path / "runs").exists()


def test_logger_failure_does_not_break_agent(tmp_path):
    selection = default_selection("test:1b")
    config = _agent_config(tmp_path)
    mock_response = LLMResponse(content="respuesta final", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = mock_response
        with patch.object(Path, "mkdir", side_effect=OSError("permission denied")):
            result = run_agent("hola", selection, config=config)

    assert "respuesta final" in result.lower()


def test_merge_cli_no_log(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from ci2lab.config import load_config, merge_cli_config

    merged = merge_cli_config(load_config(), no_log=True)
    assert merged.log_runs is False
