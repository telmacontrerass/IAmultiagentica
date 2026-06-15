import os

import pytest

from ci2lab.config import (
    DEFAULT_MODEL,
    Ci2LabConfig,
    load_config,
    merge_cli_config,
    resolve_workspace,
)


def test_load_config_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CI2LAB_MODEL", raising=False)
    # Aísla también el fallback a ~/.ci2lab/ci2lab.yaml de la máquina local.
    monkeypatch.setattr("ci2lab.config.Path.home", lambda: tmp_path)
    cfg = load_config()
    assert cfg.model == DEFAULT_MODEL
    assert cfg.tool_mode == "native"
    assert cfg.max_rounds == 25
    assert cfg.stream is True
    assert cfg.auto_confirm is False


def test_load_config_from_yaml(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci2lab.yaml").write_text(
        "model: test:7b\nmax_rounds: 10\nauto_confirm: true\n",
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.model == "test:7b"
    assert cfg.max_rounds == 10
    assert cfg.auto_confirm is True


def test_merge_cli_overrides_yaml(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci2lab.yaml").write_text("model: yaml:1b\n", encoding="utf-8")
    base = load_config()
    merged = merge_cli_config(base, model="cli:3b")
    assert merged.model == "cli:3b"


def test_merge_cli_workspace(tmp_path):
    base = Ci2LabConfig()
    merged = merge_cli_config(base, workspace=str(tmp_path))
    assert merged.workspace == str(tmp_path.resolve())


def test_workspace_cwd_conflict():
    with pytest.raises(ValueError, match="solo uno"):
        resolve_workspace(workspace=".", cwd="/tmp", config=Ci2LabConfig())


def test_env_overrides_yaml(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ci2lab.yaml").write_text("model: yaml:1b\n", encoding="utf-8")
    monkeypatch.setenv("CI2LAB_MODEL", "env:2b")
    cfg = load_config()
    assert cfg.model == "env:2b"
