from unittest.mock import patch

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.repl import run_repl


def test_repl_multi_agent_routes_each_prompt_to_orchestrator(tmp_path, monkeypatch):
    cfg = AgentConfig(cwd=str(tmp_path), stream=False, run_log_enabled=False)
    selection = default_selection("user-selected:7b")
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)

    with (
        patch("ci2lab.harness.repl.read_prompt_line", side_effect=[
            "implementa una tarea",
            "/exit",
        ]),
        patch("ci2lab.harness.repl.run_multi_agent", return_value="final multi") as run_multi_agent,
        patch("ci2lab.harness.repl.run_agent") as run_agent,
        patch("ci2lab.harness.repl.console.print"),
    ):
        run_repl(selection, cfg, session_id="test-session", multi_agent=True)

    run_multi_agent.assert_called_once_with(
        "implementa una tarea",
        selection,
        config=cfg,
    )
    run_agent.assert_not_called()


def test_repl_classic_mode_still_uses_run_agent(tmp_path, monkeypatch):
    cfg = AgentConfig(cwd=str(tmp_path), stream=False, run_log_enabled=False)
    selection = default_selection("user-selected:7b")
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)

    with (
        patch("ci2lab.harness.repl.read_prompt_line", side_effect=[
            "implementa una tarea",
            "/exit",
        ]),
        patch("ci2lab.harness.repl.run_multi_agent") as run_multi_agent,
        patch("ci2lab.harness.repl.run_agent") as run_agent,
        patch("ci2lab.harness.repl.console.print"),
    ):
        run_repl(selection, cfg, session_id="test-session", multi_agent=False)

    run_agent.assert_called_once()
    run_multi_agent.assert_not_called()
