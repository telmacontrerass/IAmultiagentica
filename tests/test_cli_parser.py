"""Tests for CLI argument parsing — shared flags before/after the subcommand."""

from __future__ import annotations

from ci2lab.cli.parser import build_parser


def test_model_flag_before_agent_subcommand_is_captured():
    # The argparse subparser-default clobber bug: `--model` given before `agent`
    # used to be silently reset to None, so the agent ran the DEFAULT model.
    args = build_parser().parse_args(["--model", "qwen2.5-coder:7b", "agent", "hola"])
    assert args.model == "qwen2.5-coder:7b"


def test_model_flag_after_agent_subcommand_is_captured():
    args = build_parser().parse_args(["agent", "--model", "qwen2.5-coder:7b", "hola"])
    assert args.model == "qwen2.5-coder:7b"


def test_model_flag_before_chat_subcommand_still_works():
    args = build_parser().parse_args(["--model", "qwen2.5-coder:7b", "chat"])
    assert args.model == "qwen2.5-coder:7b"


def test_no_model_flag_defaults_to_none():
    args = build_parser().parse_args(["agent", "hola"])
    assert args.model is None


def test_store_true_flag_before_agent_subcommand_is_captured():
    # store_true flags were clobbered to False by the same bug.
    args = build_parser().parse_args(["--multi-agent", "agent", "hola"])
    assert args.multi_agent is True
