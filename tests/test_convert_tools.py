"""Tests for docx_to_pdf and pdf_to_docx conversion tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ci2lab.harness.tools.convert import docx_to_pdf, pdf_to_docx
from ci2lab.harness.tools.docx import pandoc_available
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.tools.write_preview import preview_docx_to_pdf, preview_pdf_to_docx
from ci2lab.harness.types import AgentConfig, ToolCall


@pytest.fixture
def pandoc_skip():
    if not pandoc_available():
        pytest.skip("pandoc not installed")


@pytest.fixture
def pdf2docx_skip():
    try:
        import pdf2docx  # noqa: F401
    except ImportError:
        pytest.skip("pdf2docx not installed")


def _make_docx(path: Path, markdown: str) -> None:
    md = path.with_suffix(".md")
    md.write_text(markdown, encoding="utf-8")
    subprocess.run(
        ["pandoc", str(md), "-o", str(path)],
        check=True,
        capture_output=True,
    )
    md.unlink()


# ---------------------------------------------------------------------------
# docx_to_pdf — extension validation (no pandoc needed)
# ---------------------------------------------------------------------------

def test_docx_to_pdf_rejects_non_docx_source(tmp_path: Path) -> None:
    result = docx_to_pdf(str(tmp_path), "file.pdf", "out.pdf")
    assert result.startswith("Error:")
    assert ".docx" in result


def test_docx_to_pdf_rejects_non_pdf_output(tmp_path: Path) -> None:
    result = docx_to_pdf(str(tmp_path), "file.docx", "out.docx")
    assert result.startswith("Error:")
    assert ".pdf" in result


def test_docx_to_pdf_missing_source(tmp_path: Path) -> None:
    result = docx_to_pdf(str(tmp_path), "missing.docx", "out.pdf")
    assert result.startswith("Error:")
    assert "missing.docx" in result


# ---------------------------------------------------------------------------
# docx_to_pdf — success path (pandoc required)
# ---------------------------------------------------------------------------

def test_docx_to_pdf_creates_file(pandoc_skip, tmp_path: Path) -> None:
    docx = tmp_path / "input.docx"
    _make_docx(docx, "# Test\n\nContenido de prueba.\n")
    result = docx_to_pdf(str(tmp_path), "input.docx", "output.pdf")
    if result.startswith("Error:") and "PDF engine" in result:
        pytest.skip("No PDF engine installed for pandoc")
    assert result.startswith("Created")
    assert (tmp_path / "output.pdf").is_file()


def test_docx_to_pdf_overwrite(pandoc_skip, tmp_path: Path) -> None:
    docx = tmp_path / "doc.docx"
    _make_docx(docx, "# Overwrite\n\nTest.\n")
    out = tmp_path / "doc.pdf"
    out.write_bytes(b"placeholder")
    result = docx_to_pdf(str(tmp_path), "doc.docx", "doc.pdf")
    if result.startswith("Error:") and "PDF engine" in result:
        pytest.skip("No PDF engine installed for pandoc")
    assert result.startswith("Created")
    assert out.stat().st_size > len(b"placeholder")


# ---------------------------------------------------------------------------
# pdf_to_docx — extension validation (no pdf2docx needed)
# ---------------------------------------------------------------------------

def test_pdf_to_docx_rejects_non_pdf_source(tmp_path: Path) -> None:
    result = pdf_to_docx(str(tmp_path), "file.docx", "out.docx")
    assert result.startswith("Error:")
    assert ".pdf" in result


def test_pdf_to_docx_rejects_non_docx_output(tmp_path: Path) -> None:
    result = pdf_to_docx(str(tmp_path), "file.pdf", "out.pdf")
    assert result.startswith("Error:")
    assert ".docx" in result


def test_pdf_to_docx_missing_source(tmp_path: Path) -> None:
    result = pdf_to_docx(str(tmp_path), "missing.pdf", "out.docx")
    assert result.startswith("Error:")
    assert "missing.pdf" in result


# ---------------------------------------------------------------------------
# pdf_to_docx — missing dependency message
# ---------------------------------------------------------------------------

def test_pdf_to_docx_missing_dep_message(tmp_path: Path, monkeypatch) -> None:
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "pdf2docx":
            raise ImportError("mocked missing")
        return real_import(name, *args, **kwargs)

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(builtins, "__import__", mock_import)
    result = pdf_to_docx(str(tmp_path), "doc.pdf", "doc.docx")
    assert result.startswith("Error:")
    assert "pdf2docx" in result


# ---------------------------------------------------------------------------
# Preview functions
# ---------------------------------------------------------------------------

def test_preview_docx_to_pdf_valid(tmp_path: Path) -> None:
    src = tmp_path / "report.docx"
    src.write_bytes(b"fake docx")
    preview = preview_docx_to_pdf(str(tmp_path), "report.docx", "report.pdf")
    assert preview.is_valid
    assert preview.is_new_file
    assert "report.pdf" in (preview.new_content or "")


def test_preview_docx_to_pdf_wrong_ext(tmp_path: Path) -> None:
    preview = preview_docx_to_pdf(str(tmp_path), "file.txt", "out.pdf")
    assert not preview.is_valid
    assert "Error:" in (preview.validation_error or "")


def test_preview_docx_to_pdf_missing_source(tmp_path: Path) -> None:
    preview = preview_docx_to_pdf(str(tmp_path), "missing.docx", "out.pdf")
    assert not preview.is_valid
    assert "missing.docx" in (preview.validation_error or "")


def test_preview_pdf_to_docx_valid(tmp_path: Path) -> None:
    src = tmp_path / "data.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    preview = preview_pdf_to_docx(str(tmp_path), "data.pdf", "data.docx")
    assert preview.is_valid
    assert preview.is_new_file
    assert "data.docx" in (preview.new_content or "")


def test_preview_pdf_to_docx_overwrite_note(tmp_path: Path) -> None:
    src = tmp_path / "data.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "data.docx"
    out.write_bytes(b"existing")
    preview = preview_pdf_to_docx(str(tmp_path), "data.pdf", "data.docx")
    assert preview.is_valid
    assert not preview.is_new_file
    assert "overwritten" in (preview.new_content or "")


# ---------------------------------------------------------------------------
# Full tool execution via registry (write_tools_enabled + auto_confirm)
# ---------------------------------------------------------------------------

def test_execute_docx_to_pdf_via_registry(pandoc_skip, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ci2lab.harness.security.write_permissions.default_confirm",
        lambda _tool, _summary: True,
    )
    docx = tmp_path / "exec.docx"
    _make_docx(docx, "# Exec test\n\nBody.\n")
    cfg = AgentConfig(cwd=str(tmp_path), require_diff_preview=False, auto_confirm=True)
    result = execute_tool(
        ToolCall(
            name="docx_to_pdf",
            arguments={"source": "exec.docx", "output": "exec.pdf"},
        ),
        cfg,
    )
    if result.is_error and "PDF engine" in result.content:
        pytest.skip("No PDF engine installed for pandoc")
    assert not result.is_error
    assert (tmp_path / "exec.pdf").is_file()
