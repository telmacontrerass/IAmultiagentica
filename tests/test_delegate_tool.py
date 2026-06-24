"""Tests for the in-loop `delegate` subagent tool."""

from unittest.mock import patch

from ci2lab.harness import default_selection
from ci2lab.harness.tools.delegate import MAX_DELEGATION_DEPTH, run_delegation
from ci2lab.harness.tools.registry import DISPATCH, TOOL_NAMES, get_function_schemas
from ci2lab.harness.types import AgentConfig


def _cfg(**kw):
    selection = default_selection("test:1b")
    return AgentConfig(cwd=".", run_log_enabled=False, selection=selection, **kw)


def test_delegate_is_registered():
    assert "delegate" in TOOL_NAMES
    assert "delegate" in DISPATCH
    names = [s["function"]["name"] for s in get_function_schemas()]
    assert "delegate" in names


def test_delegate_requires_task():
    assert run_delegation(_cfg(), "   ").startswith("Error: delegate requires")


def test_delegate_depth_guard_blocks_nested_delegation():
    cfg = _cfg(delegation_depth=MAX_DELEGATION_DEPTH)
    out = run_delegation(cfg, "explore the repo")
    assert "not available inside a delegated subagent" in out


def test_delegate_needs_a_model_selection():
    cfg = AgentConfig(cwd=".", run_log_enabled=False, selection=None)
    assert "no model selection" in run_delegation(cfg, "explore the repo")


def test_delegate_runs_subagent_and_returns_only_its_output():
    cfg = _cfg()
    captured = {}

    def fake_run_agent(task_prompt, selection, *, config, messages, on_progress=None):
        # The subagent must start from a clean context: just its own system
        # prompt, with the task delivered as the user prompt — not the parent
        # conversation.
        captured["roles"] = [m["role"] for m in messages]
        captured["task"] = task_prompt
        captured["depth"] = config.delegation_depth
        captured["isolated_tokens"] = config.token_usage is not cfg.token_usage
        return "FOUND: the loop lives in loop.py"

    with patch("ci2lab.harness.multiagent.runner.run_agent", side_effect=fake_run_agent):
        out = run_delegation(cfg, "find where the agent loop lives", mode="explore")

    assert out == "FOUND: the loop lives in loop.py"
    assert captured["roles"] == ["system"]
    assert captured["task"] == "find where the agent loop lives"
    assert captured["depth"] == 1  # bumped exactly one level
    assert captured["isolated_tokens"] is True  # parent token counters untouched


def test_delegate_unknown_mode_is_rejected():
    out = run_delegation(_cfg(), "do something", mode="banana")
    assert "unknown delegate mode" in out


def test_delegate_edit_mode_maps_to_writer_role():
    cfg = _cfg()
    seen = {}

    def fake_run_agent(task_prompt, selection, *, config, messages, on_progress=None):
        seen["can_write"] = "write_file" in (config.skill_allowed_tools or set())
        return "done"

    with patch("ci2lab.harness.multiagent.runner.run_agent", side_effect=fake_run_agent):
        run_delegation(cfg, "implement the change", mode="edit")

    assert seen["can_write"] is True
