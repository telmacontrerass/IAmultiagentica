from unittest.mock import patch

from ci2lab.cli import main


def test_agent_uses_classic_flow_by_default():
    with (
        patch("ci2lab.cli.commands.agent._resolve_selection") as resolve_selection,
        patch("ci2lab.cli.commands.agent._build_config") as build_config,
        patch("ci2lab.harness.run_agent", return_value="done") as run_agent,
        patch("ci2lab.harness.multiagent.run_multi_agent") as run_multi_agent,
    ):
        resolve_selection.return_value.ollama_tag = "test:1b"
        resolve_selection.return_value.tool_mode = "fenced"
        build_config.return_value.cwd = "."

        assert main(["agent", "hello"]) == 0

    run_agent.assert_called_once()
    run_multi_agent.assert_not_called()


def test_agent_multi_agent_flag_uses_orchestrator():
    with (
        patch("ci2lab.cli.commands.agent._resolve_selection") as resolve_selection,
        patch("ci2lab.cli.commands.agent._build_config") as build_config,
        patch("ci2lab.harness.run_agent") as run_agent,
        patch("ci2lab.harness.multiagent.run_multi_agent", return_value="done") as run_multi_agent,
    ):
        resolve_selection.return_value.ollama_tag = "test:1b"
        resolve_selection.return_value.tool_mode = "fenced"
        build_config.return_value.cwd = "."

        assert main(["agent", "--multi-agent", "hello"]) == 0

    run_multi_agent.assert_called_once()
    run_agent.assert_not_called()


def test_agent_multi_agent_prints_final_answer(capsys):
    with (
        patch("ci2lab.cli.commands.agent._resolve_selection") as resolve_selection,
        patch("ci2lab.cli.commands.agent._build_config") as build_config,
        patch(
            "ci2lab.harness.multiagent.run_multi_agent",
            return_value="multi final",
        ),
    ):
        resolve_selection.return_value.ollama_tag = "test:1b"
        resolve_selection.return_value.tool_mode = "fenced"
        build_config.return_value.cwd = "."

        assert main(["agent", "--multi-agent", "hello"]) == 0

    assert "multi final" in capsys.readouterr().out
