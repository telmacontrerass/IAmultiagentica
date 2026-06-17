"""Word (.docx) read/write via pandoc."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_PANDOC_MISSING = (
    "Error: cannot process .docx because `pandoc` is missing from PATH. "
    "Install it with: winget install JohnMacFarlane.Pandoc"
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
        return f"Error: pandoc timed out reading {path.name}"
    except OSError as exc:
        return f"Error: could not run pandoc: {exc}"

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown failure").strip()
        return f"Error: pandoc could not read {path.name}: {err[:500]}"

    text = result.stdout
    if not text.strip():
        return (
            "Error: the Word document has no extractable text "
            "(empty or images only; OCR not available)."
        )
    return text


def build_docx_from_markdown(target: Path, markdown: str) -> str:
    """Write a .docx file from markdown content using pandoc."""
    pandoc = _pandoc_path()
    if not pandoc:
        return _PANDOC_MISSING

    if target.suffix.lower() != ".docx":
        return "Error: write_docx only accepts paths ending in .docx"

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
        return f"Error: pandoc timed out writing {target.name}"
    except OSError as exc:
        return f"Error: could not run pandoc: {exc}"
    finally:
        tmp_md.unlink(missing_ok=True)

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown failure").strip()
        return f"Error: pandoc could not create {target.name}: {err[:500]}"

    size = target.stat().st_size
    return f"Created {target} ({size} bytes) from markdown via pandoc"


def write_docx(cwd: str, path: str, content: str) -> str:
    """Create or overwrite a .docx from markdown content (workspace-relative path)."""
    from ci2lab.harness.tools.paths import PathViolationError, resolve_path

    try:
        resolved = resolve_path(path, cwd)
    except PathViolationError as exc:
        return f"Error: {exc}"
    return build_docx_from_markdown(resolved, content)
