import os
import sys
import tempfile
import types

from ci2lab.harness.tools.filesystem import (
    grep_search,
    read_file,
    read_document,
    write_file,
    edit_file,
    ls,
)
from ci2lab.harness.tools.paths import PathViolationError, resolve_path
from ci2lab.harness.tools.registry import execute_tool, normalize_tool_arguments
from ci2lab.harness.types import AgentConfig, ToolCall


def test_resolve_path_blocks_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            resolve_path("..", tmp)
            assert False, "debería fallar"
        except PathViolationError:
            pass


def test_read_file_null_offset_limit(tmp_path):
    (tmp_path / "config.txt").write_text("version=1.0\n", encoding="utf-8")
    text = read_file(str(tmp_path), "config.txt", offset=None, limit=None)
    assert "version" in text


def test_read_file_still_reads_code_files(tmp_path):
    (tmp_path / "main.py").write_text("print('hola')\n", encoding="utf-8")

    text = read_file(str(tmp_path), "main.py")

    assert "print('hola')" in text


def test_read_file_pdf_extracts_text(tmp_path, monkeypatch):
    class FakePage:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class FakeReader:
        def __init__(self, path):
            self.path = path
            self.pages = [FakePage("primer parrafo"), FakePage("segundo parrafo")]

    fake_pypdf = types.SimpleNamespace(PdfReader=FakeReader)
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4 fake")

    text = read_file(str(tmp_path), "doc.pdf")

    assert "[PDF page 1/2]" in text
    assert "primer parrafo" in text
    assert "segundo parrafo" in text


def test_grep_search_finds_text_inside_pdf(tmp_path, monkeypatch):
    class FakePage:
        def extract_text(self):
            return "formal register\ninformal mate"

    class FakeReader:
        def __init__(self, path):
            self.path = path
            self.pages = [FakePage()]

    fake_pypdf = types.SimpleNamespace(PdfReader=FakeReader)
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4 fake")

    text = grep_search(str(tmp_path), "formal", glob_pattern="*.pdf")

    assert "doc.pdf" in text
    assert "formal register" in text


def test_read_file_pdf_without_text_reports_ocr_needed(tmp_path, monkeypatch):
    class FakePage:
        def extract_text(self):
            return ""

    class FakeReader:
        def __init__(self, path):
            self.path = path
            self.pages = [FakePage()]

    fake_pypdf = types.SimpleNamespace(PdfReader=FakeReader)
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)
    (tmp_path / "scan.pdf").write_bytes(b"%PDF-1.4 fake")

    text = read_file(str(tmp_path), "scan.pdf")

    assert text.startswith("Error:")
    assert "OCR" in text


def test_read_document_plain_text_adds_metadata(tmp_path):
    (tmp_path / "apuntes.md").write_text("# Tema 1\nContenido", encoding="utf-8")

    text = read_document(str(tmp_path), "apuntes.md")

    assert "Documento: apuntes.md" in text
    assert "Tipo: md" in text
    assert "Texto extraido:" in text
    assert "# Tema 1" in text


def test_read_document_docx_extracts_paragraphs_and_tables(tmp_path, monkeypatch):
    class FakeStyle:
        name = "Heading 1"

    class FakeParagraph:
        def __init__(self, text, style=None):
            self.text = text
            self.style = style

    class FakeCell:
        def __init__(self, text):
            self.text = text

    class FakeRow:
        cells = [FakeCell("Criterio"), FakeCell("Puntos")]

    class FakeTable:
        rows = [FakeRow()]

    class FakeDocument:
        paragraphs = [
            FakeParagraph("Rubrica de evaluacion", FakeStyle()),
            FakeParagraph("Claridad conceptual"),
        ]
        tables = [FakeTable()]

    fake_docx = types.SimpleNamespace(Document=lambda path: FakeDocument())
    monkeypatch.setitem(sys.modules, "docx", fake_docx)
    (tmp_path / "rubrica.docx").write_bytes(b"fake docx")

    text = read_document(str(tmp_path), "rubrica.docx")

    assert "Tipo: docx" in text
    assert "[Heading 1] Rubrica de evaluacion" in text
    assert "Criterio | Puntos" in text


def test_read_document_xlsx_extracts_sheets(tmp_path, monkeypatch):
    class FakeSheet:
        title = "Notas"

        def iter_rows(self, **kwargs):
            return iter([
                ("Alumno", "Examen"),
                ("A1", 8.5),
            ])

    class FakeWorkbook:
        worksheets = [FakeSheet()]

        def close(self):
            pass

    fake_openpyxl = types.SimpleNamespace(
        load_workbook=lambda path, read_only, data_only: FakeWorkbook()
    )
    monkeypatch.setitem(sys.modules, "openpyxl", fake_openpyxl)
    (tmp_path / "notas.xlsx").write_bytes(b"fake xlsx")

    text = read_document(str(tmp_path), "notas.xlsx")

    assert "Tipo: xlsx" in text
    assert "[Sheet: Notas]" in text
    assert "Alumno | Examen" in text
    assert "A1 | 8.5" in text


def test_grep_search_finds_text_inside_docx(tmp_path, monkeypatch):
    class FakeDocument:
        paragraphs = [types.SimpleNamespace(text="feedback docente", style=None)]
        tables = []

    fake_docx = types.SimpleNamespace(Document=lambda path: FakeDocument())
    monkeypatch.setitem(sys.modules, "docx", fake_docx)
    (tmp_path / "comentarios.docx").write_bytes(b"fake docx")

    text = grep_search(str(tmp_path), "docente", glob_pattern="*.docx")

    assert "comentarios.docx" in text
    assert "feedback docente" in text


def test_execute_read_file_strips_null_optional_args(tmp_path):
    (tmp_path / "config.txt").write_text("version=1.0\n", encoding="utf-8")
    call = ToolCall(
        name="read_file",
        arguments={"path": "config.txt", "offset": None, "limit": None},
        call_id="r1",
    )
    result = execute_tool(call, AgentConfig(cwd=str(tmp_path)))
    assert not result.is_error
    assert "version" in result.content


def test_normalize_tool_arguments_drops_nulls():
    assert normalize_tool_arguments({"path": "a", "offset": None}) == {"path": "a"}


def test_read_write_edit_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        write_file(tmp, "a.txt", "hello world")
        assert "hello" in read_file(tmp, "a.txt")
        edit_file(tmp, "a.txt", "world", "ci2lab")
        assert "ci2lab" in read_file(tmp, "a.txt")
        listing = ls(tmp, ".")
        assert "a.txt" in listing
