"""Document format conversion: docx ↔ pdf."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_PANDOC_TIMEOUT_SECONDS = 120

_PANDOC_MISSING = (
    "Error: no se puede convertir porque falta `pandoc` en PATH. "
    "Instálalo con: winget install JohnMacFarlane.Pandoc"
)

_PDF2DOCX_MISSING = (
    "Error: no se puede convertir PDF a DOCX porque falta la dependencia `pdf2docx`. "
    'Instálala con: pip install pdf2docx  (o pip install -e ".[convert]")'
)


def _pandoc_path() -> str | None:
    return shutil.which("pandoc")


def docx_to_pdf(cwd: str, source: str, output: str) -> str:
    """Convert a .docx file to .pdf using pandoc."""
    from ci2lab.harness.tools.paths import PathViolationError, resolve_path

    try:
        source_path = resolve_path(source, cwd)
        output_path = resolve_path(output, cwd)
    except PathViolationError as exc:
        return f"Error: {exc}"

    if source_path.suffix.lower() != ".docx":
        return f"Error: docx_to_pdf requiere un archivo fuente .docx, no '{source_path.suffix}'"
    if output_path.suffix.lower() != ".pdf":
        return f"Error: docx_to_pdf requiere una ruta de salida .pdf, no '{output_path.suffix}'"
    if not source_path.is_file():
        return f"Error: archivo fuente no encontrado: {source}"

    pandoc = _pandoc_path()
    if not pandoc:
        return _PANDOC_MISSING

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [pandoc, str(source_path), "-o", str(output_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PANDOC_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"Error: pandoc tardó demasiado convirtiendo {source_path.name}"
    except OSError as exc:
        return f"Error: no se pudo ejecutar pandoc: {exc}"

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "fallo desconocido").strip()
        hint = (
            " Puede que falte un motor PDF (wkhtmltopdf, weasyprint, etc.)."
            if "pdf" in err.lower() or "engine" in err.lower()
            else ""
        )
        return f"Error: pandoc no pudo crear {output_path.name}: {err[:500]}{hint}"

    size = output_path.stat().st_size
    return f"Creado {output} ({size} bytes) desde {source} vía pandoc"


def pdf_to_docx(cwd: str, source: str, output: str) -> str:
    """Convert a .pdf file to .docx using pdf2docx."""
    from ci2lab.harness.tools.paths import PathViolationError, resolve_path

    try:
        source_path = resolve_path(source, cwd)
        output_path = resolve_path(output, cwd)
    except PathViolationError as exc:
        return f"Error: {exc}"

    if source_path.suffix.lower() != ".pdf":
        return f"Error: pdf_to_docx requiere un archivo fuente .pdf, no '{source_path.suffix}'"
    if output_path.suffix.lower() != ".docx":
        return f"Error: pdf_to_docx requiere una ruta de salida .docx, no '{output_path.suffix}'"
    if not source_path.is_file():
        return f"Error: archivo fuente no encontrado: {source}"

    try:
        from pdf2docx import Converter
    except ImportError:
        return _PDF2DOCX_MISSING

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        cv = Converter(str(source_path))
        cv.convert(str(output_path), start=0, end=None)
        cv.close()
    except Exception as exc:  # noqa: BLE001
        return f"Error: no se pudo convertir {source_path.name}: {exc}"

    size = output_path.stat().st_size
    return f"Creado {output} ({size} bytes) desde {source} vía pdf2docx"
