"""Document format conversion: docx ↔ pdf.

`docx_to_pdf` tries several engines in order of robustness. The first one
(LibreOffice) handles Unicode (CJK, accents, emojis) without LaTeX, which is
exactly where pandoc's default engine (pdflatex) fails. If LibreOffice is not
available, Unicode-compatible LaTeX engines (xelatex/lualatex/tectonic) are
tried, then HTML engines (weasyprint/wkhtmltopdf), leaving pdflatex as the
last resort.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

_PANDOC_TIMEOUT_SECONDS: int = 120
_SOFFICE_TIMEOUT_SECONDS: int = 180

_PANDOC_MISSING = (
    "Error: cannot convert because `pandoc` is missing from PATH. "
    "Install it with: winget install JohnMacFarlane.Pandoc"
)

_PDF2DOCX_MISSING = (
    "Error: cannot convert PDF to DOCX because the `pdf2docx` dependency is missing. "
    'Install it with: pip install pdf2docx  (or pip install -e ".[convert]")'
)

# LaTeX engines that DO accept arbitrary Unicode (unlike pdflatex).
_UNICODE_LATEX_ENGINES: tuple[str, ...] = ("xelatex", "lualatex", "tectonic")
# Engines that render via HTML/CSS (without LaTeX).
_HTML_PDF_ENGINES: tuple[str, ...] = ("weasyprint", "wkhtmltopdf", "prince")


def _pandoc_path() -> str | None:
    """Return the resolved ``pandoc`` executable path, or ``None`` if absent."""
    return shutil.which("pandoc")


def _soffice_path() -> str | None:
    """Return the first available LibreOffice executable path, or ``None``."""
    for name in ("soffice", "libreoffice", "soffice.bin"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _validate_docx(source_path: Path) -> str | None:
    """Return an error message if the .docx is not a valid Word OOXML file.

    Args:
        source_path: Path to the candidate ``.docx`` file.

    Returns:
        ``None`` if the file is a valid OOXML package, otherwise an
        ``"Error: ..."`` message explaining why it is not.
    """
    if not zipfile.is_zipfile(source_path):
        return (
            f"Error: '{source_path.name}' is not a valid .docx (not an "
            "OOXML/zip package). It may be corrupt or a renamed legacy .doc. "
            "Regenerate it (write_docx) or open and save it as a real .docx."
        )
    try:
        with zipfile.ZipFile(source_path) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return f"Error: '{source_path.name}' is corrupt and cannot be read as a .docx."
    if "word/document.xml" not in names:
        return (
            f"Error: '{source_path.name}' is a zip but does not contain "
            "word/document.xml; it is not a valid Word document."
        )
    return None


def _convert_with_soffice(soffice: str, source_path: Path, output_path: Path) -> str | None:
    """Convert with headless LibreOffice. Returns None on success, or an error.

    Args:
        soffice: Path to the LibreOffice/``soffice`` executable.
        source_path: Path to the source ``.docx`` file.
        output_path: Destination ``.pdf`` path; parent dirs are created.

    Returns:
        ``None`` on success, otherwise a short error string describing the
        LibreOffice failure.
    """
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
            return "LibreOffice timed out"
        except OSError as exc:
            return f"could not run LibreOffice: {exc}"

        produced = Path(tmp) / (source_path.stem + ".pdf")
        if result.returncode != 0 or not produced.is_file():
            return (result.stderr or result.stdout or "LibreOffice failure").strip()[:300]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(output_path))
    return None


def _convert_with_pandoc(
    pandoc: str, source_path: Path, output_path: Path, engine: str | None
) -> str | None:
    """Convert with pandoc using a specific PDF engine. None on success.

    Args:
        pandoc: Path to the ``pandoc`` executable.
        source_path: Path to the source ``.docx`` file.
        output_path: Destination ``.pdf`` path.
        engine: PDF engine to pass via ``--pdf-engine``, or ``None`` to let
            pandoc pick its default engine.

    Returns:
        ``None`` on success, otherwise a short error string describing the
        pandoc failure.
    """
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
        return "pandoc timed out"
    except OSError as exc:
        return f"could not run pandoc: {exc}"
    if result.returncode != 0 or not output_path.is_file():
        return (result.stderr or result.stdout or "unknown failure").strip()[:300]
    return None


def docx_to_pdf(cwd: str, source: str, output: str) -> str:
    """Convert a .docx file to .pdf trying several engines for robustness.

    Engines are tried in order: LibreOffice first (best fidelity and Unicode
    support without LaTeX), then pandoc with Unicode-safe LaTeX/HTML engines,
    falling back to pandoc's default ``pdflatex``.

    Args:
        cwd: The current working directory used to resolve paths.
        source: Workspace-relative path to the source ``.docx`` file.
        output: Workspace-relative destination path for the ``.pdf``.

    Returns:
        A success message naming the engine used, or an ``"Error: ..."`` message
        if validation fails or no engine could produce a PDF.
    """
    from ci2lab.harness.tools.paths import PathViolationError, resolve_path

    try:
        source_path = resolve_path(source, cwd)
        output_path = resolve_path(output, cwd)
    except PathViolationError as exc:
        return f"Error: {exc}"

    if source_path.suffix.lower() != ".docx":
        return f"Error: docx_to_pdf requires a .docx source file, not '{source_path.suffix}'"
    if output_path.suffix.lower() != ".pdf":
        return f"Error: docx_to_pdf requires a .pdf output path, not '{output_path.suffix}'"
    if not source_path.is_file():
        return f"Error: source file not found: {source}"

    invalid = _validate_docx(source_path)
    if invalid:
        return invalid

    output_path.parent.mkdir(parents=True, exist_ok=True)
    attempts: list[str] = []

    # 1) LibreOffice: maximum fidelity and Unicode without LaTeX.
    soffice = _soffice_path()
    if soffice:
        err = _convert_with_soffice(soffice, source_path, output_path)
        if err is None:
            size = output_path.stat().st_size
            return f"Created {output} ({size} bytes) from {source} via LibreOffice"
        attempts.append(f"LibreOffice: {err}")

    # 2) pandoc with several engines (Unicode-safe first).
    pandoc = _pandoc_path()
    if pandoc:
        engines: list[str | None] = []
        engine: str | None
        for engine in (*_UNICODE_LATEX_ENGINES, *_HTML_PDF_ENGINES):
            if shutil.which(engine):
                engines.append(engine)
        engines.append(None)  # pandoc chooses (pdflatex); last resort.

        for engine in engines:
            err = _convert_with_pandoc(pandoc, source_path, output_path, engine)
            if err is None:
                label = engine or "pandoc (default engine)"
                size = output_path.stat().st_size
                return f"Created {output} ({size} bytes) from {source} via {label}"
            attempts.append(f"pandoc/{engine or 'default'}: {err}")

    if not soffice and not pandoc:
        return (
            "Error: no conversion engine available. Install LibreOffice "
            "(recommended for Unicode): winget install TheDocumentFoundation.LibreOffice "
            "— or pandoc + a PDF engine (winget install JohnMacFarlane.Pandoc)."
        )

    detail = " | ".join(attempts) if attempts else "no details"
    return (
        f"Error: could not create {output_path.name}: a valid PDF engine is missing. "
        "Install LibreOffice (recommended, supports Unicode/CJK) or an engine like "
        "xelatex/weasyprint/wkhtmltopdf. Attempts: " + detail[:600]
    )


def pdf_to_docx(cwd: str, source: str, output: str) -> str:
    """Convert a .pdf file to .docx using pdf2docx.

    Args:
        cwd: The current working directory used to resolve paths.
        source: Workspace-relative path to the source ``.pdf`` file.
        output: Workspace-relative destination path for the ``.docx``.

    Returns:
        A success message describing the created file, or an ``"Error: ..."``
        message if validation fails, ``pdf2docx`` is missing, or conversion
        fails.
    """
    from ci2lab.harness.tools.paths import PathViolationError, resolve_path

    try:
        source_path = resolve_path(source, cwd)
        output_path = resolve_path(output, cwd)
    except PathViolationError as exc:
        return f"Error: {exc}"

    if source_path.suffix.lower() != ".pdf":
        return f"Error: pdf_to_docx requires a .pdf source file, not '{source_path.suffix}'"
    if output_path.suffix.lower() != ".docx":
        return f"Error: pdf_to_docx requires a .docx output path, not '{output_path.suffix}'"
    if not source_path.is_file():
        return f"Error: source file not found: {source}"

    try:
        from pdf2docx import Converter
    except ImportError:
        return _PDF2DOCX_MISSING

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        cv = Converter(str(source_path))
        cv.convert(str(output_path), start=0, end=None)
        cv.close()
    except Exception as exc:
        return f"Error: could not convert {source_path.name}: {exc}"

    size = output_path.stat().st_size
    return f"Created {output} ({size} bytes) from {source} via pdf2docx"
