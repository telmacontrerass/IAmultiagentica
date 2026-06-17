"""Tests de ayuda global del CLI."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest

from ci2lab.cli import _expand_tools_shortcut, main
from ci2lab.cli.parser import _is_global_help_request, _print_global_help

_GLOBAL_MARKERS = (
    'ci2lab "peticion"',
    "ci2lab chat",
    "ci2lab --multi-agent chat",
    "ci2lab sessions",
    "ci2lab doctor",
    "ci2lab hardware",
    "ci2lab models recommend",
    "ci2lab models install",
    "ci2lab models run",
    "ci2lab evals run",
    "--workspace",
    "--tool-mode",
    "--session",
    "--no-log",
    "--multi-agent",
    "ci2lab agent --multi-agent --model mistral:7b chat",
    "ci2lab agent --multi-agent --model llama3.1:8b chat",
    "ci2lab agent --multi-agent --model qwen2.5-coder:14b chat",
    "evals run [--live]",
    "python -m ci2lab.evals.run",
    "read_file, ls, glob, grep",
    "ANTES del subcomando",
)


def test_is_global_help_request():
    assert _is_global_help_request([])
    assert _is_global_help_request(["--help"])
    assert _is_global_help_request(["-h"])
    assert not _is_global_help_request(["hola"])
    assert not _is_global_help_request(["doctor", "--help"])
    assert not _is_global_help_request(["agent", "--help"])


@pytest.mark.parametrize("argv", [["--help"], ["-h"], []])
def test_global_help_lists_commands(capsys, argv):
    assert main(argv) == 0
    out = capsys.readouterr().out
    for marker in _GLOBAL_MARKERS:
        assert marker in out


def test_global_help_via_module_invocation():
    for flag in ("--help", "-h"):
        proc = subprocess.run(
            [sys.executable, "-m", "ci2lab", flag],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        for marker in _GLOBAL_MARKERS:
            assert marker in proc.stdout


def test_agent_shortcut_without_subcommand():
    with patch("ci2lab.cli.main._run_turn", return_value=0) as run_turn:
        assert main(["hola"]) == 0
    run_turn.assert_called_once()
    assert run_turn.call_args.args[0] == "hola"


def test_tools_shortcut_model_first_expands_to_friendly_chat():
    assert _expand_tools_shortcut(["qwen:1.8b", "tools"]) == [
        "--model", "qwen:1.8b", "--tool-mode", "fenced", "--no-stream", "chat"
    ]


def test_tools_shortcut_command_first_expands_to_friendly_chat():
    assert _expand_tools_shortcut(["tools", "qwen:1.8b"]) == [
        "--model", "qwen:1.8b", "--tool-mode", "fenced", "--no-stream", "chat"
    ]


def test_tools_shortcut_with_prompt_runs_one_turn():
    assert _expand_tools_shortcut(["qwen:1.8b", "tools", "resume", "prueba.pdf"]) == [
        "--model", "qwen:1.8b", "--tool-mode", "fenced", "--no-stream",
        "agent", "resume prueba.pdf",
    ]


def test_doctor_help_still_specific():
    with pytest.raises(SystemExit) as exc:
        main(["doctor", "--help"])
    assert exc.value.code == 0


def test_models_recommend_help_still_specific():
    with pytest.raises(SystemExit) as exc:
        main(["models", "recommend", "--help"])
    assert exc.value.code == 0


def test_print_global_help_is_ascii_only(capsys):
    _print_global_help()
    text = capsys.readouterr().out
    text.encode("cp1252")
