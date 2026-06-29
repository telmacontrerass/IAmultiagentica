from unittest.mock import patch

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.repl import _TransientProgress, run_repl
from ci2lab.harness.session import load_session


def test_repl_multi_agent_routes_each_prompt_to_orchestrator(tmp_path, monkeypatch):
    cfg = AgentConfig(cwd=str(tmp_path), stream=False, run_log_enabled=False)
    selection = default_selection("user-selected:7b")
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)

    with (
        patch(
            "ci2lab.harness.repl.read_prompt_line",
            side_effect=[
                "implement a task",
                "/exit",
            ],
        ),
        patch("ci2lab.harness.repl.run_multi_agent", return_value="final multi") as run_multi_agent,
        patch("ci2lab.harness.repl.run_agent") as run_agent,
        patch("ci2lab.harness.repl.console.print"),
    ):
        run_repl(selection, cfg, session_id="test-session", multi_agent=True)

    run_multi_agent.assert_called_once()
    args, kwargs = run_multi_agent.call_args
    assert args == ("implement a task", selection)
    assert kwargs["config"] is cfg
    assert callable(kwargs["on_progress"])
    run_agent.assert_not_called()


def test_repl_classic_mode_still_uses_run_agent(tmp_path, monkeypatch):
    cfg = AgentConfig(cwd=str(tmp_path), stream=False, run_log_enabled=False)
    selection = default_selection("user-selected:7b")
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)

    with (
        patch(
            "ci2lab.harness.repl.read_prompt_line",
            side_effect=[
                "implement a task",
                "/exit",
            ],
        ),
        patch("ci2lab.harness.repl.run_multi_agent") as run_multi_agent,
        patch("ci2lab.harness.repl.run_agent") as run_agent,
        patch("ci2lab.harness.repl.console.print"),
    ):
        run_repl(selection, cfg, session_id="test-session", multi_agent=False)

    run_agent.assert_called_once()
    assert callable(run_agent.call_args.kwargs["on_progress"])
    run_multi_agent.assert_not_called()


def test_project_repl_injects_sources_but_saves_clean_user_message(tmp_path, monkeypatch):
    cfg = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        run_log_enabled=False,
        project_id="prj_123456789abc",
    )
    selection = default_selection("user-selected:7b")
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "ci2lab.ui.projects.get_project",
        lambda project_id: {
            "id": project_id,
            "name": "Physics",
            "source_count": 2,
        },
    )
    monkeypatch.setattr(
        "ci2lab.ui.projects.project_prompt",
        lambda project_id, prompt: f"{prompt}\nPROJECT SOURCE: private physics notes",
    )

    with (
        patch(
            "ci2lab.harness.repl.read_prompt_line",
            side_effect=["Explain acceleration", "/exit"],
        ),
        patch("ci2lab.harness.repl.run_agent", return_value="Acceleration explained") as run_agent,
        patch("ci2lab.harness.repl.console.print"),
    ):
        run_repl(selection, cfg, session_id="project-session", multi_agent=False)

    sent_prompt = run_agent.call_args.args[0]
    assert "PROJECT SOURCE: private physics notes" in sent_prompt
    stored = load_session("project-session")
    assert stored is not None
    assert stored["project_id"] == cfg.project_id
    assert stored["messages"][-2]["content"] == "Explain acceleration"
    assert "private physics notes" not in stored["messages"][-2]["content"]


def test_transient_progress_reuses_one_line_and_clears_it():
    status = patch("ci2lab.harness.repl.console.status").start()
    handle = status.return_value
    try:
        progress = _TransientProgress()
        progress.update("Planning the work...")
        progress.update("Checking the result...")
        progress.clear()
    finally:
        patch.stopall()

    status.assert_called_once()
    assert status.call_args.args[0] == ("[dim italic cyan]Planning the work...[/dim italic cyan]")
    handle.start.assert_called_once()
    handle.update.assert_called_once_with(
        "[dim italic cyan]Checking the result...[/dim italic cyan]"
    )
    handle.stop.assert_called_once()
