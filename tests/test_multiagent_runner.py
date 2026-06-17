from unittest.mock import patch

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.multiagent import AgentRole, run_subagent
from ci2lab.harness.multiagent.runner import build_subagent_config


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
    assert len(messages) == 1
    assert messages[0]["role"] == "system"
    assert "Role: planner" in messages[0]["content"]
    assert "isolated subagent context" in messages[0]["content"]


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
