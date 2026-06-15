"""Word (.docx) read/write via pandoc."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_PANDOC_MISSING = (
    "Error: no se puede procesar .docx porque falta `pandoc` en PATH. "
    "Instálalo con: winget install JohnMacFarlane.Pandoc"
)

_PANDOC_TIMEOUT_SECONDS = 120


def pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def _pandoc_path() -> str | None:
    return shutil.which("pandoc")


def extract_docx_markdown(path: Path) -> str:
    """Extract markdown/plain text from a .docx file using pandoc."""
    pandoc = _pandoc_path()
    if not pandoc:
        return _PANDOC_MISSING

    try:
        result = subprocess.run(
            [pandoc, str(path), "-t", "markdown", "--wrap=none"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PANDOC_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"Error: pandoc tardó demasiado leyendo {path.name}"
    except OSError as exc:
        return f"Error: no se pudo ejecutar pandoc: {exc}"

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "fallo desconocido").strip()
        return f"Error: pandoc no pudo leer {path.name}: {err[:500]}"

    text = result.stdout
    if not text.strip():
        return (
            "Error: el documento Word no tiene texto extraíble "
            "(vacío o solo imágenes; OCR no disponible)."
        )
    return text


def build_docx_from_markdown(target: Path, markdown: str) -> str:
    """Write a .docx file from markdown content using pandoc."""
    pandoc = _pandoc_path()
    if not pandoc:
        return _PANDOC_MISSING

    if target.suffix.lower() != ".docx":
        return "Error: write_docx solo admite rutas que terminen en .docx"

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_md = target.with_name(f".{target.stem}.ci2lab.tmp.md")

    try:
        tmp_md.write_text(markdown, encoding="utf-8")
        result = subprocess.run(
            [pandoc, str(tmp_md), "-o", str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PANDOC_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"Error: pandoc tardó demasiado escribiendo {target.name}"
    except OSError as exc:
        return f"Error: no se pudo ejecutar pandoc: {exc}"
    finally:
        tmp_md.unlink(missing_ok=True)

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "fallo desconocido").strip()
        return f"Error: pandoc no pudo crear {target.name}: {err[:500]}"

    size = target.stat().st_size
    return f"Creado {target} ({size} bytes) desde markdown vía pandoc"


def write_docx(cwd: str, path: str, content: str) -> str:
    """Create or overwrite a .docx from markdown content (workspace-relative path)."""
    from ci2lab.harness.tools.paths import PathViolationError, resolve_path

    try:
        resolved = resolve_path(path, cwd)
    except PathViolationError as exc:
        return f"Error: {exc}"
    return build_docx_from_markdown(resolved, content)
