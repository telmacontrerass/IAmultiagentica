from pathlib import Path
from unittest.mock import patch

from ci2lab.cli.menu import (
    MenuOption,
    ModelChoice,
    build_model_choices,
    open_session_json,
    select_session,
    _parse_command_line,
    _run_doctor_with_ollama_install_option,
    _add_project_source_from_path,
    _projects_menu,
    _run_project_chat,
    _visible_option_window,
    run_start_menu,
    select_from_menu,
)
from ci2lab.config import Ci2LabConfig
from ci2lab.contracts import HardwareProfile, ModelSpec


def test_build_model_choices_marks_installed_and_missing():
    models = [
        ModelSpec(
            id="large",
            display_name="Large Model",
            family="test",
            categories=["coding"],
            ollama_tag="large:70b",
            vram_min_gb=48,
            ram_inference_gb=96,
            supports_tools=True,
            context_length=4096,
            tool_mode="native",
            tier="enterprise",
            benchmark_score={"general": 0.8},
        ),
        ModelSpec(
            id="small",
            display_name="Small Model",
            family="test",
            categories=["general"],
            ollama_tag="small:1b",
            vram_min_gb=1,
            ram_inference_gb=2,
            supports_tools=True,
            context_length=4096,
            tool_mode="native",
            tier="edge",
            benchmark_score={"general": 0.5},
        ),
    ]
    profile = HardwareProfile(
        ram_total_gb=16,
        ram_available_gb=12,
        vram_total_gb=0,
        vram_available_gb=0,
        gpu_name="",
        gpu_vendor="none",
        cpu_cores=8,
        os="windows",
        inference_mode="cpu",
        inference_budget_gb=10,
    )

    with (
        patch("ci2lab.cli.menu.load_model_catalog", return_value=models),
        patch(
            "ci2lab.cli.menu.fetch_installed_models",
            return_value=([{"name": "small:1b"}], None),
        ),
        patch("ci2lab.cli.menu.scan_hardware", return_value=profile),
    ):
        choices, error = build_model_choices(Ci2LabConfig())

    assert error is None
    assert choices[0].installed is True
    assert choices[0].ollama_tag == "small:1b"
    assert "(installed" in choices[0].label
    assert choices[1].installed is False
    assert "(not installed" in choices[1].label


def test_menu_chat_uses_selected_model_and_existing_runner():
    selected = ModelChoice(
        label="Small Model (installed)",
        value="small",
        catalog_id="small",
        ollama_tag="small:1b",
        installed=True,
    )
    calls = []

    with (
        patch("ci2lab.cli.menu.select_from_menu", side_effect=["chat", "exit"]),
        patch("ci2lab.cli.menu.select_model", return_value=selected),
        patch("ci2lab.cli.menu._pause"),
    ):
        result = run_start_menu(Ci2LabConfig(), command_runner=lambda args: calls.append(args) or 0)

    assert result == 0
    assert calls == [["--model", "small", "chat"]]


def test_main_menu_exposes_my_projects():
    from ci2lab.cli.menu import MAIN_OPTIONS

    project_option = next(option for option in MAIN_OPTIONS if option.value == "projects")
    assert project_option.label == "My projects"


def test_projects_menu_opens_selected_project(monkeypatch):
    project = {
        "id": "prj_123456789abc",
        "name": "Physics",
        "source_count": 2,
        "source_size_label": "1.2 MB",
    }
    monkeypatch.setattr("ci2lab.ui.projects.list_projects", lambda: [project])
    opened = []
    with (
        patch("ci2lab.cli.menu.select_from_menu", side_effect=[project["id"], "back"]),
        patch(
            "ci2lab.cli.menu._project_detail_menu",
            side_effect=lambda runtime, project_id: opened.append(project_id) or 0,
        ),
    ):
        assert _projects_menu(Ci2LabConfig()) == 0

    assert opened == [project["id"]]


def test_projects_menu_can_create_project(monkeypatch):
    created = {
        "ok": True,
        "project": {
            "id": "prj_123456789abc",
            "name": "Machine Learning",
        },
    }
    monkeypatch.setattr("ci2lab.ui.projects.list_projects", lambda: [])
    monkeypatch.setattr("ci2lab.ui.projects.create_project", lambda name: created)
    opened = []
    with (
        patch("ci2lab.cli.menu.select_from_menu", side_effect=["create", "back"]),
        patch("ci2lab.cli.menu._ask_text", return_value="Machine Learning"),
        patch(
            "ci2lab.cli.menu._project_detail_menu",
            side_effect=lambda runtime, project_id: opened.append(project_id) or 0,
        ),
    ):
        assert _projects_menu(Ci2LabConfig()) == 0

    assert opened == ["prj_123456789abc"]


def test_add_project_source_reads_selected_local_file(tmp_path, monkeypatch):
    source = tmp_path / "notes.txt"
    source.write_text("course notes", encoding="utf-8")
    captured = {}

    def fake_add(project_id, payload):
        captured["project_id"] = project_id
        captured["payload"] = payload
        return {
            "ok": True,
            "source": {"name": "notes.txt", "size_label": "12 B"},
        }

    monkeypatch.setattr("ci2lab.ui.projects.add_project_source", fake_add)
    with patch("ci2lab.cli.menu._ask_text", return_value=str(source)):
        assert _add_project_source_from_path("prj_123456789abc") is True

    assert captured["project_id"] == "prj_123456789abc"
    assert captured["payload"]["name"] == "notes.txt"
    assert captured["payload"]["content_base64"]


def test_run_project_chat_uses_project_workspace_and_id(monkeypatch):
    selected = ModelChoice(
        label="Small Model",
        value="small",
        catalog_id="small",
        ollama_tag="small:1b",
        installed=True,
    )
    project = {
        "id": "prj_123456789abc",
        "name": "Physics",
        "source_count": 3,
        "workspace": "/tmp/physics-project",
    }
    selection = type("Selection", (), {"ollama_tag": "small:1b"})()
    config = type("Config", (), {"project_id": None})()
    captured = {}

    monkeypatch.setattr("ci2lab.ui.projects.get_project", lambda project_id: project)
    with (
        patch("ci2lab.cli.menu.select_model", return_value=selected),
        patch("ci2lab.pipeline.prepare_session", return_value=(None, selection)),
        patch("ci2lab.pipeline.build_agent_config", return_value=config) as build,
        patch(
            "ci2lab.harness.repl.run_repl",
            side_effect=lambda sel, cfg, **kwargs: captured.update(
                {"selection": sel, "config": cfg, **kwargs}
            ),
        ),
    ):
        assert _run_project_chat(
            Ci2LabConfig(),
            project["id"],
            session_id="session-1",
            multi_agent=True,
        ) == 0

    assert build.call_args.kwargs["cwd"] == project["workspace"]
    assert config.project_id == project["id"]
    assert captured["session_id"] == "session-1"
    assert captured["multi_agent"] is True


def test_menu_command_mode_runs_manual_args():
    calls = []

    with (
        patch("ci2lab.cli.menu.select_from_menu", side_effect=["command_mode", "exit"]),
        patch("ci2lab.cli.menu._ask_text", return_value='ci2lab agent "list Python files"'),
        patch("ci2lab.cli.menu._pause"),
    ):
        result = run_start_menu(Ci2LabConfig(), command_runner=lambda args: calls.append(args) or 0)

    assert result == 0
    assert calls == [["agent", "list Python files"]]


def test_parse_command_line_preserves_windows_paths_and_strips_quotes():
    assert _parse_command_line(r'--workspace C:\Users\Pablo chat') == [
        "--workspace",
        r"C:\Users\Pablo",
        "chat",
    ]
    assert _parse_command_line('agent "resume this project"') == [
        "agent",
        "resume this project",
    ]


def test_selector_uses_raw_no_spam_fallback_without_prompt_toolkit():
    options = [MenuOption("One", "First option", "one")]
    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("ci2lab.cli.menu._select_from_menu_app", side_effect=ImportError),
        patch("ci2lab.cli.menu._select_from_menu_raw", return_value="one") as raw,
    ):
        assert select_from_menu("Test", options) == "one"
    raw.assert_called_once()


def test_visible_option_window_scrolls_to_selected_item():
    with patch("ci2lab.cli.menu.shutil.get_terminal_size") as term_size:
        term_size.return_value.lines = 12
        start, end = _visible_option_window(
            total=20,
            selected_index=15,
            subtitle="workspace",
        )

    assert start > 0
    assert start <= 15 < end
    assert end <= 20


def test_doctor_does_not_offer_ollama_install_when_found():
    calls = []
    with patch(
        "ci2lab.cli.menu.ollama_install_info",
        return_value={"executable": "C:/Ollama/ollama.exe", "models_dir": "models"},
    ), patch("ci2lab.cli.menu._confirm") as confirm:
        assert _run_doctor_with_ollama_install_option(lambda args: calls.append(args) or 0) == 0

    assert calls == [["doctor"]]
    confirm.assert_not_called()


def test_doctor_offers_ollama_install_when_missing():
    calls = []
    completed = type("Completed", (), {"returncode": 0})()
    with (
        patch(
            "ci2lab.cli.menu.ollama_install_info",
            return_value={"executable": None, "models_dir": "models"},
        ),
        patch(
            "ci2lab.cli.menu._ollama_install_action",
            return_value=("test installer", ["installer", "ollama"]),
        ),
        patch("ci2lab.cli.menu._confirm", return_value=True),
        patch("ci2lab.cli.menu.subprocess.run", return_value=completed) as run,
    ):
        result = _run_doctor_with_ollama_install_option(
            lambda args: calls.append(args) or 0
        )

    assert result == 0
    assert calls == [["doctor"]]
    run.assert_called_once_with(["installer", "ollama"], check=False)


def test_open_session_json_uses_session_file(tmp_path: Path, monkeypatch):
    session_file = tmp_path / "abc123.json"
    session_file.write_text('{"id": "abc123"}', encoding="utf-8")
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)

    opened = []
    with patch("ci2lab.cli.menu._open_path", side_effect=lambda path: opened.append(path)):
        assert open_session_json("abc123") == 0

    assert opened == [session_file]


def test_select_session_uses_title_as_label(tmp_path: Path, monkeypatch):
    from ci2lab.harness.session import save_session

    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    save_session(
        "abc123",
        messages=[{"role": "user", "content": "read P1_T1_IE.pdf"}],
        model_tag="qwen2.5vl:7b",
        cwd="/tmp",
    )
    captured: list[MenuOption] = []

    def _capture(_title, options, **kwargs):
        captured.extend(options)
        return "abc123"

    with patch("ci2lab.cli.menu.select_from_menu", side_effect=_capture):
        row = select_session()

    assert row is not None
    assert row["id"] == "abc123"
    assert captured[0].label == "P1 T1 IE pdf"
    assert "abc123" in captured[0].description
