"""Opt-in, non-destructive checks against an existing local Ollama model."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from ci2lab.harness import AgentConfig, default_selection, run_agent
from ci2lab.harness.llm_client import LLMClient
from ci2lab.runtime.ollama import fetch_installed_model_names, ollama_model_names_equivalent

pytestmark = pytest.mark.ollama_integration


def _existing_model(env_name: str = "CI2LAB_TEST_OLLAMA_MODEL") -> str:
    model = os.environ.get(env_name, "").strip()
    if not model:
        pytest.skip(f"set {env_name} to an already-installed model")
    names, error = fetch_installed_model_names(timeout=2.0)
    if error:
        pytest.skip(f"Ollama is unavailable: {error}")
    if not any(ollama_model_names_equivalent(model, name) for name in names):
        pytest.skip(f"configured model is not installed: {model}")
    return model


def test_ollama_show_existing_model():
    model = _existing_model()
    result = subprocess.run(
        ["ollama", "show", model],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr


def test_ollama_chat_existing_model():
    selection = default_selection(_existing_model())
    response = LLMClient(selection).chat([{"role": "user", "content": "Reply with OK."}])
    assert response.content.strip()


def test_ollama_agent_without_required_tools(tmp_path):
    selection = default_selection(_existing_model())
    result = run_agent(
        "Reply briefly with OK.",
        selection,
        config=AgentConfig(cwd=str(tmp_path), max_rounds=2, stream=False, run_log_enabled=False),
    )
    assert result.strip()


def test_ollama_agent_requires_real_tool_execution(tmp_path):
    selection = default_selection(_existing_model("CI2LAB_TEST_OLLAMA_TOOL_MODEL"))
    result = run_agent(
        "Use a tool to inspect the current directory, then report what happened.",
        selection,
        config=AgentConfig(
            cwd=str(tmp_path),
            max_rounds=5,
            stream=False,
            auto_confirm=True,
            run_log_enabled=True,
            runs_dir=str(tmp_path / "runs"),
            require_tool_execution=True,
            verify_final_answer=False,
        ),
    )
    assert not result.startswith("REQUIRED_TOOL_NOT_EXECUTED")
    logs = list((tmp_path / "runs").rglob("tool_calls.jsonl"))
    assert logs
    entries = [json.loads(line) for line in logs[-1].read_text(encoding="utf-8").splitlines()]
    assert any(entry["ok"] for entry in entries)
    assert all(entry["source_protocol"] for entry in entries)
