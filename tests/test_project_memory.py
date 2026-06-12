"""Tests for project memory file loading."""

from __future__ import annotations

from pathlib import Path

from ci2lab.harness.project_memory import load_project_memory


def test_load_project_memory_merges_files(tmp_path: Path) -> None:
    tmp_path.joinpath("CI2LAB.md").write_text("Use pytest.", encoding="utf-8")
    ci2lab_dir = tmp_path / ".ci2lab"
    ci2lab_dir.mkdir()
    ci2lab_dir.joinpath("AGENTS.md").write_text("Never commit secrets.", encoding="utf-8")

    memory = load_project_memory(str(tmp_path))
    assert "## Project memory" in memory
    assert "Use pytest." in memory
    assert "Never commit secrets." in memory


def test_load_project_memory_empty_when_missing(tmp_path: Path) -> None:
    assert load_project_memory(str(tmp_path)) == ""
