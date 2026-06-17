"""Tests unitarios para ci2lab/harness/tools/docx_writer.py."""

from __future__ import annotations

import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Path:
    """Workspace temporal con una plantilla mínima."""
    return tmp_path


@pytest.fixture()
def simple_template(tmp_workspace: Path) -> Path:
    """Crea un DOCX de plantilla con marcadores básicos."""
    pytest.importorskip("docx", reason="python-docx no instalado")
    from docx import Document

    tpl_dir = tmp_workspace / "templates"
    tpl_dir.mkdir()
    tpl = tpl_dir / "plantilla.docx"

    doc = Document()
    doc.add_paragraph("Nombre: {{nombre}}")
    doc.add_paragraph("Fecha: {{fecha}}")
    doc.add_paragraph("Sin marcador")
    # Tabla con marcador
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].paragraphs[0].add_run("{{ciudad}}")
    table.rows[0].cells[1].paragraphs[0].add_run("descripción")
    doc.save(str(tpl))
    return tpl


# ---------------------------------------------------------------------------
# Tests de fill_docx_template
# ---------------------------------------------------------------------------

class TestFillDocxTemplate:
    def test_basic_substitution(self, tmp_workspace: Path, simple_template: Path) -> None:
        """Sustituye marcadores en párrafos y tablas."""
        from ci2lab.harness.tools.docx_writer import fill_docx_template
        from docx import Document

        output = tmp_workspace / "output.docx"
        result = fill_docx_template(
            cwd=str(tmp_workspace),
            template="templates/plantilla.docx",
            output="output.docx",
            fields={"nombre": "Clara", "fecha": "2026-06-14", "ciudad": "Madrid"},
        )

        assert "Error" not in result
        assert output.is_file()

        doc = Document(str(output))
        texts = [p.text for p in doc.paragraphs]
        assert "Nombre: Clara" in texts
        assert "Fecha: 2026-06-14" in texts
        assert "Sin marcador" in texts

        # Tabla
        cell_text = doc.tables[0].rows[0].cells[0].paragraphs[0].text
        assert cell_text == "Madrid"

    def test_no_fields(self, tmp_workspace: Path, simple_template: Path) -> None:
        """Sin campos la plantilla se copia tal cual."""
        from ci2lab.harness.tools.docx_writer import fill_docx_template
        from docx import Document

        output = tmp_workspace / "sin_campos.docx"
        result = fill_docx_template(
            cwd=str(tmp_workspace),
            template="templates/plantilla.docx",
            output="sin_campos.docx",
            fields={},
        )

        assert "Error" not in result
        doc = Document(str(output))
        assert any("{{nombre}}" in p.text for p in doc.paragraphs)

    def test_creates_output_directory(self, tmp_workspace: Path, simple_template: Path) -> None:
        """Crea directorios intermedios del output si no existen."""
        from ci2lab.harness.tools.docx_writer import fill_docx_template

        result = fill_docx_template(
            cwd=str(tmp_workspace),
            template="templates/plantilla.docx",
            output="subdir/nested/out.docx",
            fields={"nombre": "Test"},
        )

        assert "Error" not in result
        assert (tmp_workspace / "subdir" / "nested" / "out.docx").is_file()

    def test_success_message_contains_substitution_count(
        self, tmp_workspace: Path, simple_template: Path
    ) -> None:
        """The success message includes the number of substitutions."""
        from ci2lab.harness.tools.docx_writer import fill_docx_template

        result = fill_docx_template(
            cwd=str(tmp_workspace),
            template="templates/plantilla.docx",
            output="conteo.docx",
            fields={"nombre": "X", "fecha": "Y", "ciudad": "Z"},
        )

        assert "3 substitutions" in result or "3 substitution" in result

    def test_missing_template(self, tmp_workspace: Path) -> None:
        """Error claro si la plantilla no existe."""
        pytest.importorskip("docx", reason="python-docx no instalado")
        from ci2lab.harness.tools.docx_writer import fill_docx_template

        result = fill_docx_template(
            cwd=str(tmp_workspace),
            template="no_existe.docx",
            output="out.docx",
            fields={},
        )

        assert result.startswith("Error")
        assert "no_existe.docx" in result

    def test_output_same_as_template_rejected(
        self, tmp_workspace: Path, simple_template: Path
    ) -> None:
        """El output no puede ser la misma ruta que la plantilla."""
        from ci2lab.harness.tools.docx_writer import fill_docx_template

        result = fill_docx_template(
            cwd=str(tmp_workspace),
            template="templates/plantilla.docx",
            output="templates/plantilla.docx",
            fields={"nombre": "X"},
        )

        assert result.startswith("Error")
        assert "misma ruta" in result

    def test_result_contains_kb(self, tmp_workspace: Path, simple_template: Path) -> None:
        """El mensaje de éxito incluye el tamaño en KB."""
        from ci2lab.harness.tools.docx_writer import fill_docx_template

        result = fill_docx_template(
            cwd=str(tmp_workspace),
            template="templates/plantilla.docx",
            output="kb_test.docx",
            fields={"nombre": "A"},
        )

        assert "KB" in result


# ---------------------------------------------------------------------------
# Tests de preview_fill_docx
# ---------------------------------------------------------------------------

class TestPreviewFillDocx:
    def test_valid_preview_shows_fields(
        self, tmp_workspace: Path, simple_template: Path
    ) -> None:
        """El preview muestra la plantilla, el output y los campos."""
        from ci2lab.harness.tools.docx_writer import preview_fill_docx

        preview = preview_fill_docx(
            str(tmp_workspace),
            {
                "template": "templates/plantilla.docx",
                "output": "output/resultado.docx",
                "fields": {"nombre": "Clara", "fecha": "2026"},
            },
        )

        assert preview.is_valid
        content = preview.new_content or ""
        assert "nombre" in content
        assert "Clara" in content
        assert "fecha" in content

    def test_missing_template_invalid(self, tmp_workspace: Path) -> None:
        """Preview inválido si la plantilla no existe."""
        pytest.importorskip("docx", reason="python-docx no instalado")
        from ci2lab.harness.tools.docx_writer import preview_fill_docx

        preview = preview_fill_docx(
            str(tmp_workspace),
            {"template": "fantasma.docx", "output": "out.docx", "fields": {}},
        )

        assert not preview.is_valid
        assert "fantasma.docx" in (preview.validation_error or "")

    def test_no_template_param_invalid(self, tmp_workspace: Path) -> None:
        """Preview inválido si falta el parámetro template."""
        pytest.importorskip("docx", reason="python-docx no instalado")
        from ci2lab.harness.tools.docx_writer import preview_fill_docx

        preview = preview_fill_docx(str(tmp_workspace), {"output": "out.docx", "fields": {}})

        assert not preview.is_valid

    def test_non_docx_template_invalid(self, tmp_workspace: Path) -> None:
        """Preview inválido si la plantilla no es .docx."""
        pytest.importorskip("docx", reason="python-docx no instalado")
        (tmp_workspace / "plantilla.pdf").touch()
        from ci2lab.harness.tools.docx_writer import preview_fill_docx

        preview = preview_fill_docx(
            str(tmp_workspace),
            {"template": "plantilla.pdf", "output": "out.docx", "fields": {}},
        )

        assert not preview.is_valid
        assert ".pdf" in (preview.validation_error or "")

    def test_new_file_flag(self, tmp_workspace: Path, simple_template: Path) -> None:
        """is_new_file=True si el output no existe todavía."""
        from ci2lab.harness.tools.docx_writer import preview_fill_docx

        preview = preview_fill_docx(
            str(tmp_workspace),
            {"template": "templates/plantilla.docx", "output": "nuevo.docx", "fields": {}},
        )

        assert preview.is_valid
        assert preview.is_new_file

    def test_existing_file_flag(self, tmp_workspace: Path, simple_template: Path) -> None:
        """is_new_file=False si el output ya existe."""
        from ci2lab.harness.tools.docx_writer import fill_docx_template, preview_fill_docx

        fill_docx_template(
            cwd=str(tmp_workspace),
            template="templates/plantilla.docx",
            output="existente.docx",
            fields={},
        )

        preview = preview_fill_docx(
            str(tmp_workspace),
            {"template": "templates/plantilla.docx", "output": "existente.docx", "fields": {}},
        )

        assert preview.is_valid
        assert not preview.is_new_file


# ---------------------------------------------------------------------------
# Tests de _replace_in_paragraph
# ---------------------------------------------------------------------------

class TestReplaceInParagraph:
    def test_simple_replacement(self) -> None:
        pytest.importorskip("docx", reason="python-docx no instalado")
        from docx import Document
        from ci2lab.harness.tools.docx_writer import _replace_in_paragraph

        doc = Document()
        para = doc.add_paragraph()
        para.add_run("Hola {{nombre}}, bienvenido a {{ciudad}}.")

        count = _replace_in_paragraph(para, {"nombre": "Ana", "ciudad": "Sevilla"})

        assert count == 2
        assert para.runs[0].text == "Hola Ana, bienvenido a Sevilla."

    def test_no_match_returns_zero(self) -> None:
        pytest.importorskip("docx", reason="python-docx no instalado")
        from docx import Document
        from ci2lab.harness.tools.docx_writer import _replace_in_paragraph

        doc = Document()
        para = doc.add_paragraph("Texto sin marcadores.")

        count = _replace_in_paragraph(para, {"nombre": "Ana"})

        assert count == 0
        assert para.text == "Texto sin marcadores."
