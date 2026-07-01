"""Tests for the Codex adapter's command construction and error parsing.

These need no Codex binary — they exercise the pure helpers, and in particular
pin the ``--oss`` placement fix (it must attach to the ``exec`` subcommand, not
before it, or Codex falls back to the ChatGPT account).
"""

from __future__ import annotations

from pathlib import Path

from ci2lab.bench.adapters.base import render_command_template
from ci2lab.bench.adapters.codex import _build_command, _find_error, _find_error_text


def test_template_prompt_as_arg() -> None:
    cmd, stdin = render_command_template(
        "codex exec -m {model} --json {prompt}",
        prompt="find the code",
        model="qwen2.5-coder:32b",
        workspace=Path("/ws"),
    )
    assert cmd == ["codex", "exec", "-m", "qwen2.5-coder:32b", "--json", "find the code"]
    assert stdin is None


def test_template_prompt_via_stdin_when_absent() -> None:
    cmd, stdin = render_command_template(
        "codex exec -m {model}", prompt="hello world", model="m", workspace=Path("/ws")
    )
    assert cmd == ["codex", "exec", "-m", "m"]
    assert stdin == "hello world"


def test_template_workspace_substitution() -> None:
    ws = Path("/ws")
    cmd, stdin = render_command_template(
        "codex exec --cd {workspace} {prompt}", prompt="p", model="m", workspace=ws
    )
    assert str(ws) in cmd
    assert cmd[-1] == "p"
    assert stdin is None


def test_oss_flag_is_after_exec() -> None:
    cmd = _build_command(
        "do the task",
        model="qwen2.5-coder:32b",
        oss=True,
        extra_args=[],
        binary="codex",
        workspace=Path("/ws"),
    )
    assert cmd[0] == "codex"
    assert cmd[1] == "exec"
    assert "--oss" in cmd
    assert cmd.index("--oss") > cmd.index("exec")
    assert cmd[cmd.index("--model") + 1] == "qwen2.5-coder:32b"
    assert cmd[-1] == "do the task"  # prompt is the final positional arg


def test_no_oss_and_empty_model_omitted() -> None:
    cmd = _build_command(
        "p", model="", oss=False, extra_args=[], binary="codex", workspace=Path("/ws")
    )
    assert "--oss" not in cmd
    assert "--model" not in cmd
    assert cmd[-1] == "p"


def test_oss_adds_local_provider_after_oss() -> None:
    cmd = _build_command(
        "p",
        model="m",
        oss=True,
        local_provider="ollama",
        extra_args=[],
        binary="codex",
        workspace=Path("/ws"),
    )
    assert "--local-provider" in cmd
    assert cmd[cmd.index("--local-provider") + 1] == "ollama"
    assert cmd.index("--local-provider") == cmd.index("--oss") + 1


def test_no_local_provider_without_oss() -> None:
    cmd = _build_command(
        "p",
        model="m",
        oss=False,
        local_provider="ollama",
        extra_args=[],
        binary="codex",
        workspace=Path("/ws"),
    )
    assert "--local-provider" not in cmd


def test_extra_args_and_binary_override() -> None:
    cmd = _build_command(
        "p",
        model="m",
        oss=False,
        extra_args=["-c", "model_provider=oss"],
        binary="/opt/codex",
        workspace=Path("/ws"),
    )
    assert cmd[0] == "/opt/codex"
    assert "-c" in cmd
    assert "model_provider=oss" in cmd
    # extra args precede the prompt
    assert cmd.index("model_provider=oss") < cmd.index("p")


def test_find_error_from_chatgpt_account_rejection() -> None:
    events = [{"detail": "The 'qwen2.5-coder:32b' model is not supported when using ..."}]
    assert _find_error(events) is not None
    assert "not supported" in (_find_error(events) or "")


def test_find_error_nested_error_object() -> None:
    events = [{"error": {"message": "rate limited"}}]
    assert _find_error(events) == "rate limited"


def test_find_error_text_single_object() -> None:
    assert _find_error_text('{"detail": "boom"}') == "boom"
    assert _find_error_text("not json") is None


def test_find_error_absent_on_normal_events() -> None:
    events = [{"type": "message", "text": "hello"}, {"usage": {"input_tokens": 10}}]
    assert _find_error(events) is None
