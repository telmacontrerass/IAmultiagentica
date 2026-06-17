"""Document format conversion: docx ↔ pdf.

`docx_to_pdf` intenta varios motores en orden de robustez. El primero
(LibreOffice) maneja Unicode (CJK, acentos, emojis) sin LaTeX, que es justo
donde el motor por defecto de pandoc (pdflatex) falla. Si LibreOffice no está
disponible, se prueban motores LaTeX compatibles con Unicode (xelatex/lualatex/
tectonic) y luego motores HTML (weasyprint/wkhtmltopdf), dejando pdflatex como
último recurso.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

_PANDOC_TIMEOUT_SECONDS = 120
_SOFFICE_TIMEOUT_SECONDS = 180

_PANDOC_MISSING = (
    "Error: no se puede convertir porque falta `pandoc` en PATH. "
    "Instálalo con: winget install JohnMacFarlane.Pandoc"
)

_PDF2DOCX_MISSING = (
    "Error: no se puede convertir PDF a DOCX porque falta la dependencia `pdf2docx`. "
    'Instálala con: pip install pdf2docx  (o pip install -e ".[convert]")'
)

# Motores LaTeX que SÍ aceptan Unicode arbitrario (a diferencia de pdflatex).
_UNICODE_LATEX_ENGINES = ("xelatex", "lualatex", "tectonic")
# Motores que renderizan vía HTML/CSS (sin LaTeX).
_HTML_PDF_ENGINES = ("weasyprint", "wkhtmltopdf", "prince")


def _pandoc_path() -> str | None:
    return shutil.which("pandoc")


def _soffice_path() -> str | None:
    for name in ("soffice", "libreoffice", "soffice.bin"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _validate_docx(source_path: Path) -> str | None:
    """Devuelve un mensaje de error si el .docx no es un Word OOXML válido."""
    if not zipfile.is_zipfile(source_path):
        return (
            f"Error: '{source_path.name}' no es un .docx válido (no es un paquete "
            "OOXML/zip). Puede estar corrupto o ser un .doc antiguo renombrado. "
            "Vuelve a generarlo (write_docx) o ábrelo y guárdalo como .docx real."
        )
    try:
        with zipfile.ZipFile(source_path) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return f"Error: '{source_path.name}' está corrupto y no se puede leer como .docx."
    if "word/document.xml" not in names:
        return (
            f"Error: '{source_path.name}' es un zip pero no contiene "
            "word/document.xml; no es un documento Word válido."
        )
    return None


def _convert_with_soffice(soffice: str, source_path: Path, output_path: Path) -> str | None:
    """Convierte con LibreOffice headless. Devuelve None si tuvo éxito, o un error."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            result = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp,
                    str(source_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_SOFFICE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "LibreOffice tardó demasiado"
        except OSError as exc:
            return f"no se pudo ejecutar LibreOffice: {exc}"

        produced = Path(tmp) / (source_path.stem + ".pdf")
        if result.returncode != 0 or not produced.is_file():
            return (result.stderr or result.stdout or "fallo de LibreOffice").strip()[:300]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(output_path))
    return None


def _convert_with_pandoc(
    pandoc: str, source_path: Path, output_path: Path, engine: str | None
) -> str | None:
    """Convierte con pandoc usando un motor PDF concreto. None si éxito."""
    cmd = [pandoc, str(source_path), "-o", str(output_path)]
    if engine:
        cmd.append(f"--pdf-engine={engine}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PANDOC_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "pandoc tardó demasiado"
    except OSError as exc:
        return f"no se pudo ejecutar pandoc: {exc}"
    if result.returncode != 0 or not output_path.is_file():
        return (result.stderr or result.stdout or "fallo desconocido").strip()[:300]
    return None


def docx_to_pdf(cwd: str, source: str, output: str) -> str:
    """Convert a .docx file to .pdf trying several engines for robustness."""
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

    invalid = _validate_docx(source_path)
    if invalid:
        return invalid

    output_path.parent.mkdir(parents=True, exist_ok=True)
    attempts: list[str] = []

    # 1) LibreOffice: máxima fidelidad y Unicode sin LaTeX.
    soffice = _soffice_path()
    if soffice:
        err = _convert_with_soffice(soffice, source_path, output_path)
        if err is None:
            size = output_path.stat().st_size
            return f"Creado {output} ({size} bytes) desde {source} vía LibreOffice"
        attempts.append(f"LibreOffice: {err}")

    # 2) pandoc con varios motores (Unicode-safe primero).
    pandoc = _pandoc_path()
    if pandoc:
        engines: list[str | None] = []
        for engine in (*_UNICODE_LATEX_ENGINES, *_HTML_PDF_ENGINES):
            if shutil.which(engine):
                engines.append(engine)
        engines.append(None)  # pandoc elige (pdflatex); último recurso.

        for engine in engines:
            err = _convert_with_pandoc(pandoc, source_path, output_path, engine)
            if err is None:
                label = engine or "pandoc (motor por defecto)"
                size = output_path.stat().st_size
                return f"Creado {output} ({size} bytes) desde {source} vía {label}"
            attempts.append(f"pandoc/{engine or 'default'}: {err}")

    if not soffice and not pandoc:
        return (
            "Error: no hay motor de conversión disponible. Instala LibreOffice "
            "(recomendado para Unicode): winget install TheDocumentFoundation.LibreOffice "
            "— o pandoc + un motor PDF (winget install JohnMacFarlane.Pandoc)."
        )

    detail = " | ".join(attempts) if attempts else "sin detalles"
    return (
        f"Error: no se pudo crear {output_path.name}: falta un motor PDF válido. "
        "Instala LibreOffice (recomendado, soporta Unicode/CJK) o un motor como "
        "xelatex/weasyprint/wkhtmltopdf. Intentos: " + detail[:600]
    )


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
