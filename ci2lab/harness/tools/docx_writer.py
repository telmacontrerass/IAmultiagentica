"""
Herramienta fill_docx_template: genera un DOCX a partir de una plantilla
y un diccionario de campos {{marcador}} → valor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ci2lab.harness.tools.paths import PathViolationError, resolve_path
from ci2lab.harness.tools.write_preview import WritePreview


# ---------------------------------------------------------------------------
# Preview (sin ejecutar nada en disco)
# ---------------------------------------------------------------------------

def preview_fill_docx(cwd: str, args: dict[str, Any]) -> WritePreview:
    """
    Construye un WritePreview descriptivo para fill_docx_template.

    No lee ni escribe nada en disco; solo valida que la plantilla exista
    y genera el texto de confirmación que verá el usuario.
    """
    template = str(args.get("template", "")).strip()
    output = str(args.get("output", "")).strip()
    fields: dict[str, str] = {
        str(k): str(v) for k, v in (args.get("fields") or {}).items()
    }

    if not template:
        return WritePreview(
            path=output or "(sin output)",
            is_new_file=True,
            diff="",
            validation_error="Error: parámetro 'template' requerido",
        )
    if not output:
        return WritePreview(
            path="(sin output)",
            is_new_file=True,
            diff="",
            validation_error="Error: parámetro 'output' requerido",
        )

    # Validar que la plantilla existe
    try:
        template_path = resolve_path(template, cwd)
    except PathViolationError as exc:
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error=str(exc),
        )

    if not template_path.is_file():
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error=f"Error: plantilla no encontrada: {template}",
        )
    if template_path.suffix.lower() != ".docx":
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error=(
                f"Error: la plantilla debe ser un .docx, "
                f"no '{template_path.suffix}'"
            ),
        )

    # Validar que el output no coincide con la plantilla
    try:
        output_path = resolve_path(output, cwd)
    except PathViolationError as exc:
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error=str(exc),
        )

    if output_path == template_path:
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error="Error: output no puede ser la misma ruta que la plantilla",
        )

    if output_path.suffix.lower() != ".docx":
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error=(
                f"Error: el output debe tener extensión .docx, "
                f"no '{output_path.suffix}'"
            ),
        )

    # Construir texto descriptivo del preview
    lines = [
        f"Plantilla : {template}",
        f"Output    : {output} ({'existente — se sobreescribe' if output_path.is_file() else 'archivo nuevo'})",
        "",
    ]
    if fields:
        lines.append("Campos a sustituir:")
        for key, value in fields.items():
            lines.append(f"  {{{{{key}}}}}  →  {value}")
    else:
        lines.append("(no se proporcionaron campos — se copiará la plantilla sin cambios)")

    return WritePreview(
        path=str(output_path.relative_to(Path(cwd).resolve()))
        if output_path.is_relative_to(Path(cwd).resolve())
        else output,
        is_new_file=not output_path.is_file(),
        diff="",
        new_content="\n".join(lines),
    )


# ---------------------------------------------------------------------------
# Sustitución de marcadores en un párrafo DOCX
# ---------------------------------------------------------------------------

def _replace_in_paragraph(paragraph: Any, fields: dict[str, str]) -> int:
    """
    Sustituye {{clave}} → valor en un párrafo, manejando runs partidos.

    python-docx puede partir el texto de un marcador entre varios runs
    (fragmentos de texto con formato distinto). La estrategia:
      1. Obtener el texto completo del párrafo.
      2. Sustituir en el texto completo.
      3. Si hubo cambios, poner el resultado en el primer run y vaciar el resto.

    Esto preserva el formato del primer run (fuente, negrita, tamaño)
    pero pierde variaciones de formato dentro del mismo párrafo. Aceptable en v1.
    """
    full_text = paragraph.text
    new_text = full_text
    count = 0
    for key, value in fields.items():
        placeholder = f"{{{{{key}}}}}"
        if placeholder in new_text:
            new_text = new_text.replace(placeholder, str(value))
            count += 1

    if count == 0:
        return 0

    if paragraph.runs:
        paragraph.runs[0].text = new_text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(new_text)

    return count


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def fill_docx_template(
    cwd: str,
    template: str,
    output: str,
    fields: dict[str, str],
) -> str:
    """
    Genera un DOCX rellenando una plantilla con los campos dados.

    Retorna siempre un string: mensaje de éxito o "Error: ...".
    """
    try:
        from docx import Document
    except ImportError:
        return (
            "Error: falta la dependencia python-docx. "
            "Ejecuta: pip install -e '.'"
        )

    # Resolver rutas (ya validadas en preview, pero re-validamos por seguridad)
    try:
        template_path = resolve_path(template, cwd)
        output_path = resolve_path(output, cwd)
    except PathViolationError as exc:
        return f"Error: {exc}"

    if not template_path.is_file():
        return f"Error: plantilla no encontrada: {template}"
    if template_path == output_path:
        return "Error: output no puede ser la misma ruta que la plantilla"

    # Abrir la plantilla
    try:
        doc = Document(str(template_path))
    except Exception as exc:  # noqa: BLE001
        return f"Error: no se pudo abrir la plantilla {template}: {exc}"

    # Crear directorio de output si no existe
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Sustituir marcadores en párrafos sueltos
    total = 0
    for paragraph in doc.paragraphs:
        total += _replace_in_paragraph(paragraph, fields)

    # Sustituir marcadores en tablas
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    total += _replace_in_paragraph(paragraph, fields)

    # Guardar
    try:
        doc.save(str(output_path))
    except Exception as exc:  # noqa: BLE001
        return f"Error: no se pudo guardar el documento en {output}: {exc}"

    size_kb = round(output_path.stat().st_size / 1024, 1)
    return (
        f"Documento generado: {output} "
        f"({total} sustitución{'es' if total != 1 else ''}, {size_kb} KB)"
    )
