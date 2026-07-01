"""Tests for the Codex adapter's command construction and error parsing.

These need no Codex binary — they exercise the pure helpers, and in particular
pin the ``--oss`` placement fix (it must attach to the ``exec`` subcommand, not
before it, or Codex falls back to the ChatGPT account).
"""

from __future__ import annotations

from pathlib import Path

from ci2lab.bench.adapters.codex import _build_command, _find_error, _find_error_text


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
