"""Tests for Word (.docx) read/write via pandoc."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ci2lab.harness.tools.docx import (
    build_docx_from_markdown,
    extract_docx_markdown,
    pandoc_available,
    write_docx,
)
from ci2lab.harness.tools.filesystem import read_file
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall


@pytest.fixture
def pandoc_skip():
    if not pandoc_available():
        pytest.skip("pandoc not installed")


def _make_docx(path: Path, markdown: str) -> None:
    md = path.with_suffix(".md")
    md.write_text(markdown, encoding="utf-8")
    subprocess.run(
        ["pandoc", str(md), "-o", str(path)],
        check=True,
        capture_output=True,
    )
    md.unlink()


def test_extract_docx_markdown(pandoc_skip, tmp_path: Path) -> None:
    docx = tmp_path / "sample.docx"
    _make_docx(docx, "# Hola\n\nPárrafo de prueba.\n")
    text = extract_docx_markdown(docx)
    assert "Hola" in text
    assert "Párrafo" in text


def test_read_file_handles_docx(pandoc_skip, tmp_path: Path) -> None:
    docx = tmp_path / "readme.docx"
    _make_docx(docx, "# Título\n\nContenido.\n")
    output = read_file(str(tmp_path), "readme.docx")
    assert "Título" in output
    assert "|" in output  # numbered lines


def test_write_docx_creates_file(pandoc_skip, tmp_path: Path) -> None:
    result = write_docx(
        str(tmp_path),
        "out.docx",
        "# Nuevo\n\nDocumento creado.\n",
    )
    assert result.startswith("Created")
    assert (tmp_path / "out.docx").is_file()


def test_write_docx_rejects_non_docx_extension(tmp_path: Path) -> None:
    result = write_docx(str(tmp_path), "out.txt", "# x\n")
    assert "Error:" in result


def test_execute_write_docx_with_approval(pandoc_skip, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ci2lab.harness.security.write_permissions.default_confirm",
        lambda _tool, _summary: True,
    )
    cfg = AgentConfig(cwd=str(tmp_path), require_diff_preview=False, auto_confirm=True)
    result = execute_tool(
        ToolCall(
            name="write_docx",
            arguments={"path": "report.docx", "content": "# Report\n\nBody.\n"},
        ),
        cfg,
    )
    assert not result.is_error
    assert (tmp_path / "report.docx").is_file()


def test_build_docx_roundtrip(pandoc_skip, tmp_path: Path) -> None:
    target = tmp_path / "round.docx"
    md = "# Roundtrip\n\nSecond line.\n"
    msg = build_docx_from_markdown(target, md)
    assert "Created" in msg
    back = extract_docx_markdown(target)
    assert "Roundtrip" in back
