from unittest.mock import patch

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.multiagent import AgentRole, run_subagent
from ci2lab.harness.multiagent.runner import (
    ROLE_MAX_ROUNDS,
    build_role_anchor,
    build_subagent_config,
    build_subagent_system_prompt,
)


def test_build_subagent_config_filters_tools_without_mutating_parent():
    parent = AgentConfig(cwd=".", stream=True, session_id="session-1")

    subagent = build_subagent_config(AgentRole.RESEARCHER, parent)

    assert parent.skill_allowed_tools is None
    assert parent.stream is True
    assert parent.session_id == "session-1"
    assert subagent.stream is False
    assert subagent.session_id is None
    assert subagent.skill_allowed_tools is not None
    assert "read_file" in subagent.skill_allowed_tools
    assert "write_file" not in subagent.skill_allowed_tools


def test_build_subagent_config_applies_role_round_budget():
    parent = AgentConfig(cwd=".", max_rounds=25)

    planner = build_subagent_config(AgentRole.PLANNER, parent)
    researcher = build_subagent_config(AgentRole.RESEARCHER, parent)
    coder = build_subagent_config(AgentRole.PYTHON_CODER, parent)

    assert planner.max_rounds == ROLE_MAX_ROUNDS[AgentRole.PLANNER]
    assert researcher.max_rounds == ROLE_MAX_ROUNDS[AgentRole.RESEARCHER]
    assert coder.max_rounds == ROLE_MAX_ROUNDS[AgentRole.PYTHON_CODER]
    assert parent.max_rounds == 25


def test_build_subagent_config_never_exceeds_parent_round_budget():
    parent = AgentConfig(cwd=".", max_rounds=3)

    subagent = build_subagent_config(AgentRole.PYTHON_CODER, parent)

    assert subagent.max_rounds == 3


def test_build_subagent_config_intersects_skill_and_role_tools():
    parent = AgentConfig(
        cwd=".",
        stream=True,
        session_id="session-1",
        skill_allowed_tools=frozenset({"web_fetch", "read_file"}),
    )

    subagent = build_subagent_config(AgentRole.RESEARCHER, parent)

    assert parent.skill_allowed_tools == frozenset({"web_fetch", "read_file"})
    assert subagent.skill_allowed_tools == frozenset({"read_file"})
    assert "web_fetch" not in subagent.skill_allowed_tools
    assert "grep" not in subagent.skill_allowed_tools


def test_build_subagent_config_keeps_empty_intersection_blocked():
    parent = AgentConfig(
        cwd=".",
        skill_allowed_tools=frozenset({"web_fetch"}),
    )

    subagent = build_subagent_config(AgentRole.RESEARCHER, parent)

    assert subagent.skill_allowed_tools == frozenset()


def test_subagent_system_prompt_includes_english_role_purpose():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".")

    prompt = build_subagent_system_prompt(
        AgentRole.RESEARCHER,
        selection,
        config,
    )

    assert "## Role Anchor" in prompt
    assert "You are currently acting as researcher." in prompt
    assert "Your purpose in this phase is: Gather evidence" in prompt
    assert "Do not implement changes" in prompt
    assert "Expected output:" in prompt


def test_run_subagent_uses_isolated_system_context_and_role_tools():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=True, session_id="session-1")

    with patch("ci2lab.harness.multiagent.runner.run_agent") as mock_run_agent:
        mock_run_agent.return_value = "plan ready"

        result = run_subagent(
            AgentRole.PLANNER,
            "Plan this change",
            selection,
            config,
        )

    assert result.role == AgentRole.PLANNER
    assert result.task == "Plan this change"
    assert result.output == "plan ready"

    _, args, kwargs = mock_run_agent.mock_calls[0]
    assert args[0] == "Plan this change"
    subagent_config = kwargs["config"]
    messages = kwargs["messages"]

    assert subagent_config is not config
    assert subagent_config.session_id is None
    assert subagent_config.stream is False
    assert subagent_config.skill_allowed_tools == frozenset()
    assert subagent_config.role_anchor == build_role_anchor(AgentRole.PLANNER)
    assert len(messages) == 1
    assert messages[0]["role"] == "system"
    assert "Role: planner" in messages[0]["content"]
    assert "You are currently acting as planner." in messages[0]["content"]
    assert "isolated subagent context" in messages[0]["content"]
    assert "BLOCKED:" in messages[0]["content"]
    assert "Do not keep retrying the same action" in messages[0]["content"]


def test_subagent_role_anchor_is_passed_to_run_agent():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=True)

    with patch("ci2lab.harness.multiagent.runner.run_agent") as mock_run_agent:
        mock_run_agent.return_value = "done"

        run_subagent(
            AgentRole.VALIDATOR,
            "Validate this change",
            selection,
            config,
        )

    _, _, kwargs = mock_run_agent.mock_calls[0]
    subagent_config = kwargs["config"]
    assert subagent_config.role_anchor == build_role_anchor(AgentRole.VALIDATOR)
    assert "Validate the current result using tests or deterministic checks." in subagent_config.role_anchor


def test_run_subagent_passes_user_selected_model_to_run_agent():
    selection = default_selection("user-selected:7b")
    config = AgentConfig(cwd=".")

    with patch("ci2lab.harness.multiagent.runner.run_agent") as mock_run_agent:
        mock_run_agent.return_value = "done"

        run_subagent(
            AgentRole.RESEARCHER,
            "Research this",
            selection,
            config,
        )

    _, args, kwargs = mock_run_agent.mock_calls[0]
    assert args[1] is selection
    assert kwargs["messages"][0]["content"].count("user-selected:7b") >= 1


def test_run_subagent_captures_internal_console_output(capsys):
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=True, session_id="session-1")

    def noisy_run_agent(*args, **kwargs):
        from ci2lab.console import console

        console.print("internal subagent output")
        return "captured result"

    with patch("ci2lab.harness.multiagent.runner.run_agent", side_effect=noisy_run_agent):
        result = run_subagent(
            AgentRole.REVIEWER,
            "Review this",
            selection,
            config,
        )

    assert result.output == "captured result"
    assert "internal subagent output" not in capsys.readouterr().out
