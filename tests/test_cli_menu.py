from pathlib import Path
from unittest.mock import patch

from ci2lab.cli.menu import (
    MenuOption,
    ModelChoice,
    build_model_choices,
    open_session_json,
    _parse_command_line,
    _run_doctor_with_ollama_install_option,
    _visible_option_window,
    run_start_menu,
    select_from_menu,
)
from ci2lab.config import Ci2LabConfig
from ci2lab.contracts import HardwareProfile, ModelSpec


def test_build_model_choices_marks_installed_and_missing():
    models = [
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
