"""P3.1 — V-02: falsos positivos por substring 'token' en nombres legitimos."""

from __future__ import annotations

from pathlib import Path

import pytest

from ci2lab.harness.tools.secret_files import is_sensitive_path
from ci2lab.harness.types import AgentConfig, ToolCall
from ci2lab.security.engine import evaluate_tool_gate

_ALLOWED_NAMES = (
    "normal_tokenized_name.txt",
    "tokenizer.py",
    "auth_tokenizer_tests.py",
    "mytokensample.txt",
    "tokenization_notes.md",
)

_BLOCKED_NAMES = (
    "api_token.txt",
    "github-token.txt",
    ".env.local",
    "secret_key.json",
    "openai_api_key.txt",
    "credentials.json",
    "credential.txt",
    "id_rsa",
    "private_key.pem",
    "passwords.txt",
    "secrets.yml",
)


@pytest.mark.parametrize("name", _ALLOWED_NAMES)
def test_allowed_names_not_sensitive(tmp_path: Path, name: str):
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ok\n", encoding="utf-8")
    assert not is_sensitive_path(target.resolve(), workspace=tmp_path)


@pytest.mark.parametrize("name", _BLOCKED_NAMES)
def test_blocked_names_still_sensitive(tmp_path: Path, name: str):
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret-data\n", encoding="utf-8")
    assert is_sensitive_path(target.resolve(), workspace=tmp_path)


@pytest.mark.parametrize("name", _BLOCKED_NAMES)
def test_ci2lab_gate_blocks_real_secrets(workspace: Path, name: str):
    config = AgentConfig(cwd=str(workspace), security_engine="ci2lab")
    gate = evaluate_tool_gate("read_file", {"path": name}, config)
    assert gate.blocked
    assert gate.matched_rule == "hard:secret_file"


@pytest.mark.parametrize("name", _BLOCKED_NAMES)
def test_claude_experimental_gate_blocks_real_secrets(workspace: Path, name: str):
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
    )
    gate = evaluate_tool_gate("read_file", {"path": name}, config)
    assert gate.blocked
    assert gate.matched_rule == "hard:secret_file"


@pytest.mark.parametrize("name", _ALLOWED_NAMES)
def test_claude_experimental_gate_allows_false_positive_names(workspace: Path, name: str):
    target = workspace / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("visible\n", encoding="utf-8")
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
    )
    gate = evaluate_tool_gate("read_file", {"path": name}, config)
    assert not gate.blocked


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    for name in _BLOCKED_NAMES:
        target = ws / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("blocked-content\n", encoding="utf-8")
    return ws


def test_execute_tool_read_allowed_tokenized_name(workspace: Path):
    from ci2lab.harness.tools.registry import execute_tool

    path = "normal_tokenized_name.txt"
    (workspace / path).write_text("visible\n", encoding="utf-8")
    config = AgentConfig(cwd=str(workspace), security_engine="claude_experimental")
    result = execute_tool(
        ToolCall(name="read_file", arguments={"path": path}, call_id="r1"),
        config,
    )
    assert not result.is_error
    assert "visible" in result.content
