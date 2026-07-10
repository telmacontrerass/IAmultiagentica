import json
from subprocess import CompletedProcess
from unittest.mock import patch

from ci2lab.cli import main
from ci2lab.router.catalog import load_model_catalog
from ci2lab.router.imported_models import (
    build_imported_profile,
    render_ollama_modelfile,
    save_imported_model_profile,
)
from ci2lab.router.selection import build_model_selection

from tests.test_router_selection import _profile


def _glm_profile(path: str = "models/glm/GLM-4-9B-0414-Q4_K_M.gguf"):
    return build_imported_profile(
        model_id="glm-4-9b-q4",
        repo="unsloth/GLM-4-9B-0414-GGUF",
        filename="GLM-4-9B-0414-Q4_K_M.gguf",
        local_path=path,
        family="glm4",
        template_id="glm4-chat",
        context_length=16384,
        tool_mode="fenced",
    )


def test_glm_modelfile_uses_template_stops_and_context():
    modelfile = render_ollama_modelfile(_glm_profile())

    assert "FROM models/glm/GLM-4-9B-0414-Q4_K_M.gguf" in modelfile
    assert 'TEMPLATE """\n[gMASK]<sop>{{ if .System }}<|system|>' in modelfile
    assert "[gMASK]<sop>{{ if .System }}<|system|>" in modelfile
    assert "<|user|>" in modelfile
    assert "{{ .Prompt }}<|assistant|>" in modelfile
    assert "PARAMETER num_ctx 16384" in modelfile
    assert "PARAMETER temperature 0.1" in modelfile
    assert 'PARAMETER stop "<|user|>"' in modelfile
    assert 'PARAMETER stop "<|assistant|>"' in modelfile
    assert 'PARAMETER stop "<|system|>"' in modelfile
    assert 'PARAMETER stop "<|observation|>"' in modelfile
    assert 'PARAMETER stop "<|endoftext|>"' in modelfile
    assert 'PARAMETER stop "<eop>"' in modelfile


def test_import_gguf_dry_run_prints_modelfile_without_ollama_or_metadata(
    tmp_path,
    monkeypatch,
    capsys,
):
    gguf = tmp_path / "model.gguf"
    gguf.write_text("fake", encoding="utf-8")
    registry = tmp_path / "imported_models.json"
    monkeypatch.setenv("CI2LAB_IMPORTED_MODELS_PATH", str(registry))

    with patch("ci2lab.router.imported_models.subprocess.run") as run:
        result = main(
            [
                "models",
                "import-gguf",
                "--repo",
                "unsloth/GLM-4-9B-0414-GGUF",
                "--file",
                "GLM-4-9B-0414-Q4_K_M.gguf",
                "--path",
                str(gguf),
                "--id",
                "glm-4-9b-q4",
                "--family",
                "glm4",
                "--template",
                "glm4-chat",
                "--ctx",
                "16384",
                "--tool-mode",
                "fenced",
                "--dry-run",
            ]
        )

    assert result == 0
    output = capsys.readouterr().out
    assert f"FROM {gguf.resolve()}" in output
    assert 'TEMPLATE """\n[gMASK]<sop>{{ if .System }}<|system|>' in output
    assert "PARAMETER num_ctx 16384" in output
    run.assert_not_called()
    assert not registry.exists()


def test_import_gguf_rejects_invalid_ollama_model_name(tmp_path, capsys):
    gguf = tmp_path / "model.gguf"
    gguf.write_text("fake", encoding="utf-8")

    result = main(
        [
            "models",
            "import-gguf",
            "--repo",
            "unsloth/GLM-4-9B-0414-GGUF",
            "--file",
            "GLM-4-9B-0414-Q4_K_M.gguf",
            "--path",
            str(gguf),
            "--id",
            "glm 4 chat",
            "--family",
            "glm4",
            "--template",
            "glm4-chat",
            "--ctx",
            "16384",
            "--dry-run",
        ]
    )

    assert result == 1
    assert "Invalid model id for Ollama" in capsys.readouterr().out


def test_import_gguf_saves_metadata_after_ollama_create(tmp_path, monkeypatch):
    gguf = tmp_path / "model.gguf"
    gguf.write_text("fake", encoding="utf-8")
    registry = tmp_path / "imported_models.json"
    monkeypatch.setenv("CI2LAB_IMPORTED_MODELS_PATH", str(registry))

    with patch(
        "ci2lab.router.imported_models.subprocess.run",
        return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    ) as run:
        result = main(
            [
                "models",
                "import-gguf",
                "--repo",
                "unsloth/GLM-4-9B-0414-GGUF",
                "--file",
                "GLM-4-9B-0414-Q4_K_M.gguf",
                "--path",
                str(gguf),
                "--id",
                "glm-4-9b-q4",
                "--family",
                "glm4",
                "--template",
                "glm4-chat",
                "--ctx",
                "16384",
                "--tool-mode",
                "fenced",
            ]
        )

    assert result == 0
    run.assert_called_once()
    assert run.call_args.kwargs["encoding"] == "utf-8"
    assert run.call_args.kwargs["errors"] == "replace"
    assert run.call_args.kwargs["text"] is True
    data = json.loads(registry.read_text(encoding="utf-8"))
    model = data["models"][0]
    assert model["id"] == "glm-4-9b-q4"
    assert model["source"]["repo"] == "unsloth/GLM-4-9B-0414-GGUF"
    assert model["context_length"] == 16384
    assert model["tool_mode"] == "fenced"


def test_imported_model_resolution_uses_profile_context_and_tool_mode(tmp_path, monkeypatch):
    registry = tmp_path / "imported_models.json"
    save_imported_model_profile(_glm_profile(), path=registry)
    monkeypatch.setenv("CI2LAB_IMPORTED_MODELS_PATH", str(registry))
    monkeypatch.delenv("CI2LAB_NUM_CTX", raising=False)

    selection = build_model_selection("glm-4-9b-q4", profile=_profile())

    assert selection.ollama_tag == "glm-4-9b-q4"
    assert selection.context_length == 16384
    assert selection.tool_mode == "fenced"
    assert selection.temperature == 0.1
    assert "Imported model profile" in selection.reason


def test_imported_model_tool_mode_override_still_wins(tmp_path, monkeypatch):
    registry = tmp_path / "imported_models.json"
    save_imported_model_profile(_glm_profile(), path=registry)
    monkeypatch.setenv("CI2LAB_IMPORTED_MODELS_PATH", str(registry))

    selection = build_model_selection(
        "glm-4-9b-q4",
        tool_mode_override="native",
        profile=_profile(),
    )

    assert selection.tool_mode == "native"


def test_context_length_priority_cli_env_profile_default(tmp_path, monkeypatch):
    registry = tmp_path / "imported_models.json"
    save_imported_model_profile(_glm_profile(), path=registry)
    monkeypatch.setenv("CI2LAB_IMPORTED_MODELS_PATH", str(registry))
    monkeypatch.setenv("CI2LAB_NUM_CTX", "8192")

    cli_selection = build_model_selection(
        "glm-4-9b-q4",
        context_length_override=32768,
        profile=_profile(),
    )
    env_selection = build_model_selection("glm-4-9b-q4", profile=_profile())

    monkeypatch.delenv("CI2LAB_NUM_CTX")
    profile_selection = build_model_selection("glm-4-9b-q4", profile=_profile())

    assert cli_selection.context_length == 32768
    assert env_selection.context_length == 8192
    assert profile_selection.context_length == 16384


def test_catalog_model_still_resolves_without_imported_registry(monkeypatch):
    monkeypatch.delenv("CI2LAB_IMPORTED_MODELS_PATH", raising=False)
    monkeypatch.delenv("CI2LAB_NUM_CTX", raising=False)

    selection = build_model_selection("qwen2.5-coder:7b", profile=_profile())

    assert selection.model_id == "qwen2.5-coder-7b"
    assert selection.ollama_tag == "qwen2.5-coder:7b"
    assert selection.tool_mode == "native"


def test_bundled_model_catalog_is_unchanged_json_list():
    catalog = load_model_catalog()

    assert catalog
    assert any(model.id == "qwen2.5-coder-7b" for model in catalog)
