from unittest.mock import MagicMock, patch

from ci2lab.cli import main
from ci2lab.cli.commands.models import _install_commands, _resolve_allowed_model
from ci2lab.contracts import HardwareProfile
from ci2lab.router.catalog import load_model_catalog


def test_models_list_prints_imported_alias_and_tag(tmp_path, monkeypatch, capsys):
    registry = tmp_path / "imported_models.json"
    registry.write_text(
        '{"models":[{"id":"glm4","backend":"ollama",'
        '"ollama_tag":"ci2lab/glm-4-9b-0414:q4_k_m","source":{},'
        '"family":"glm4","template_id":"glm4-chat","context_length":16384,'
        '"tool_mode":"fenced"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CI2LAB_IMPORTED_MODELS_PATH", str(registry))

    assert main(["models", "list"]) == 0
    output = capsys.readouterr().out
    assert "glm4" in output
    assert "ci2lab/glm-4-9b-0414:q4_k_m" in output


def _profile() -> HardwareProfile:
    return HardwareProfile(
        ram_total_gb=8.0,
        ram_available_gb=4.0,
        vram_total_gb=0.0,
        vram_available_gb=0.0,
        gpu_name="Apple Silicon GPU",
        gpu_vendor="apple",
        cpu_cores=8,
        os="darwin",
        inference_mode="gpu",
        inference_budget_gb=3.6,
        inference_budget_theoretical_gb=3.6,
        inference_budget_available_gb=2.4,
        memory_pressure=False,
    )


def test_install_commands_use_ollama_tag_and_catalog_id():
    model = next(model for model in load_model_catalog() if model.id == "qwen2.5-coder-1.5b")

    commands = _install_commands(model)

    assert commands["pull"] == "ollama pull qwen2.5-coder:1.5b"
    assert commands["ollama_run"] == "ollama run qwen2.5-coder:1.5b"
    assert commands["ci2lab_chat"] == "ci2lab --model qwen2.5-coder-1.5b chat"


def test_resolve_allowed_model_accepts_id_and_ollama_tag():
    by_id = _resolve_allowed_model("qwen2.5-coder-1.5b", profile=_profile())
    by_tag = _resolve_allowed_model("qwen2.5-coder:1.5b", profile=_profile())

    assert by_id is not None
    assert by_tag is not None
    assert by_id.id == by_tag.id == "qwen2.5-coder-1.5b"


def test_models_run_opens_ollama_with_selected_tag():
    completed = MagicMock(returncode=0)

    with (
        patch("ci2lab.cli.commands.models.scan_hardware", return_value=_profile()),
        patch("ci2lab.cli.commands.models.subprocess.run", return_value=completed) as run,
    ):
        result = main(["models", "run", "qwen2.5-coder-1.5b"])

    assert result == 0
    run.assert_called_once_with(["ollama", "run", "qwen2.5-coder:1.5b"], check=False)
