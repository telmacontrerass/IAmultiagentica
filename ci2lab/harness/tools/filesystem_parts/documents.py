"""Document readers and text extraction helpers."""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

MAX_READ_LINES = 2000
MAX_PDF_PAGES = 100
MAX_SPREADSHEET_ROWS = 200
MAX_SPREADSHEET_COLS = 30
MAX_PRESENTATION_SLIDES = 200
MAX_DOCUMENT_CHARS = 120_000

TEXT_DOCUMENT_SUFFIXES = frozenset({
    ".csv",
    ".json",
    ".log",
    ".md",
    ".rst",
    ".text",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
})
OFFICE_DOCUMENT_SUFFIXES = frozenset({".docx", ".pptx", ".xlsx"})
SUPPORTED_DOCUMENT_SUFFIXES = (
    TEXT_DOCUMENT_SUFFIXES | OFFICE_DOCUMENT_SUFFIXES | frozenset({".pdf"})
)


def numbered_lines(text: str, offset: int = 1, limit: int | None = None) -> str:
    lines = text.splitlines()
    start = max(1, offset if offset is not None else 1)
    end = start + (limit or MAX_READ_LINES) - 1
    slice_lines = lines[start - 1 : end]
    numbered = [f"{i + start:6d}|{line}" for i, line in enumerate(slice_lines)]
    if len(lines) > end:
        numbered.append(f"... ({len(lines) - end} more lines; use offset/limit)")
    return "\n".join(numbered) if numbered else "(empty file)"


def extract_document_text(path: Path, *, include_metadata: bool = False) -> str:
    """Extract text from supported teaching/document formats."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        facade = _filesystem_facade()
        text = facade.extract_pdf_text(path)
        sections = (
            facade._pdf_section_count(path)
            if include_metadata and not text.startswith("Error:")
            else None
        )
    elif suffix == ".docx":
        text = extract_docx_text(path)
        sections = "unknown"
    elif suffix == ".pptx":
        text, sections = extract_pptx_text(path)
    elif suffix == ".xlsx":
        text, sections = extract_xlsx_text(path)
    elif suffix in {".csv", ".tsv"}:
        text = extract_csv_text(path)
        sections = "1 table"
    elif suffix in TEXT_DOCUMENT_SUFFIXES or not suffix:
        text = path.read_text(encoding="utf-8", errors="replace")
        sections = "plain text"
    elif not include_metadata:
        text = path.read_text(encoding="utf-8", errors="replace")
        sections = "plain text"
    else:
        return (
            f"Error: unsupported format for document reading: "
            f"{suffix or '(no extension)'}"
        )

    if text.startswith("Error:") or not include_metadata:
        return text

    text = truncate_document_text(text)
    return (
        f"Document: {path.name}\n"
        f"Type: {suffix.lstrip('.') or 'text'}\n"
        f"Pages/sections: {sections or 'unknown'}\n"
        "Extracted text:\n\n"
        f"{text}"
    ).strip()


def truncate_document_text(text: str) -> str:
    if len(text) <= MAX_DOCUMENT_CHARS:
        return text
    return (
        text[:MAX_DOCUMENT_CHARS].rstrip()
        + f"\n\n... (text truncated; limit {MAX_DOCUMENT_CHARS} characters)"
    )


def pdf_section_count(path: Path) -> str | None:
    try:
        from pypdf import PdfReader

        return f"{len(PdfReader(str(path)).pages)} pages"
    except Exception:  # noqa: BLE001
        return None


def extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF file, returning an Error: string on failure."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return (
            "Error: cannot read PDF because the `pypdf` dependency is missing. "
            "Reinstall the project to enable PDF support."
        )

    logging.getLogger("pypdf").setLevel(logging.ERROR)

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        return f"Error: could not open the PDF {path}: {exc}"

    total_pages = len(reader.pages)
    page_count = min(total_pages, MAX_PDF_PAGES)
    chunks: list[str] = []
    has_extractable_text = False
    for index in range(page_count):
        page = reader.pages[index]
        page_number = index + 1
        chunks.append(f"[PDF page {page_number}/{total_pages}]")
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            page_text = f"Error extracting text from this page: {exc}"
        page_text = page_text.strip()
        if page_text:
            has_extractable_text = True
        chunks.append(page_text or "(no extractable text on this page)")

    if total_pages > page_count:
        chunks.append(
            f"... ({total_pages - page_count} more pages; PDF limit {MAX_PDF_PAGES})"
        )

    if not has_extractable_text:
        return (
            "Error: the PDF has no extractable text. It may be a scanned PDF; "
            "OCR is needed to read images."
        )
    return "\n".join(chunks).strip()


def pdf_has_extractable_text(
    path: Path,
    *,
    min_chars: int = 40,
    max_pages: int = 5,
) -> bool:
    """Return True when the PDF has enough embedded text for ``read_document``."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return False

    logging.getLogger("pypdf").setLevel(logging.ERROR)

    try:
        reader = PdfReader(str(path))
    except Exception:  # noqa: BLE001
        return False

    total_chars = 0
    for index in range(min(len(reader.pages), max_pages)):
        try:
            page_text = (reader.pages[index].extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            continue
        total_chars += len(page_text)
        if total_chars >= min_chars:
            return True
    return False


def pdf_needs_vision(path: Path) -> bool:
    """Return True for scanned/image-only PDFs that need a vision model."""
    return path.suffix.lower() == ".pdf" and not pdf_has_extractable_text(path)


def extract_docx_text(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        from ci2lab.harness.tools.docx import extract_docx_markdown

        return extract_docx_markdown(path)

    try:
        document = Document(str(path))
    except Exception as exc:  # noqa: BLE001
        return f"Error: could not open the DOCX {path}: {exc}"

    chunks: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
        if style_name.lower().startswith("heading"):
            chunks.append(f"[{style_name}] {text}")
        else:
            chunks.append(text)

    for table_index, table in enumerate(document.tables, start=1):
        rows = []
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            rows.append(" | ".join(cells))
        if rows:
            chunks.append(f"[Table {table_index}]")
            chunks.extend(rows)

    return "\n".join(chunks).strip() or "(DOCX document with no extractable text)"


def extract_pptx_text(path: Path) -> tuple[str, str]:
    try:
        from pptx import Presentation
    except ImportError:
        return (
            "Error: cannot read PPTX because the `python-pptx` dependency is missing. "
            "Reinstall the project to enable PowerPoint support."
        ), "desconocido"

    try:
        presentation = Presentation(str(path))
    except Exception as exc:  # noqa: BLE001
        return f"Error: could not open the PPTX {path}: {exc}", "desconocido"

    total_slides = len(presentation.slides)
    chunks: list[str] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        if slide_index > MAX_PRESENTATION_SLIDES:
            break
        slide_text: list[str] = []
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                text = str(shape.text).strip()
                if text:
                    slide_text.append(text)
        chunks.append(f"[Slide {slide_index}]")
        chunks.append("\n".join(slide_text) if slide_text else "(no extractable text)")

    if total_slides > MAX_PRESENTATION_SLIDES:
        chunks.append(
            f"... ({total_slides - MAX_PRESENTATION_SLIDES} more slides; "
            f"limite {MAX_PRESENTATION_SLIDES})"
        )

    return "\n".join(chunks).strip(), f"{total_slides} slides"


def extract_xlsx_text(path: Path) -> tuple[str, str]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return (
            "Error: cannot read XLSX because the `openpyxl` dependency is missing. "
            "Reinstall the project to enable Excel support."
        ), "desconocido"

    try:
        workbook = load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return f"Error: could not open the XLSX {path}: {exc}", "desconocido"

    chunks: list[str] = []
    for sheet in workbook.worksheets:
        chunks.append(f"[Sheet: {sheet.title}]")
        row_count = 0
        for row in sheet.iter_rows(
            max_row=MAX_SPREADSHEET_ROWS,
            max_col=MAX_SPREADSHEET_COLS,
            values_only=True,
        ):
            row_count += 1
            values = trim_empty_tail(["" if value is None else str(value) for value in row])
            if not values:
                continue
            chunks.append(" | ".join(values).rstrip())
        if row_count >= MAX_SPREADSHEET_ROWS:
            chunks.append(
                f"... (sheet truncated; limit {MAX_SPREADSHEET_ROWS} rows x "
                f"{MAX_SPREADSHEET_COLS} columns)"
            )

    close = getattr(workbook, "close", None)
    if callable(close):
        close()
    return "\n".join(chunks).strip(), f"{len(workbook.worksheets)} sheets"


def extract_csv_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    delimiter = "\t" if path.suffix.lower() == ".tsv" else None
    sample = text[:4096]
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample).delimiter
        except csv.Error:
            delimiter = ","
    rows: list[str] = []
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    for index, row in enumerate(reader, start=1):
        if index > MAX_SPREADSHEET_ROWS:
            rows.append(f"... (tabla truncada; limite {MAX_SPREADSHEET_ROWS} filas)")
            break
        values = trim_empty_tail(row)
        if values:
            rows.append(" | ".join(values))
    return "\n".join(rows).strip() or "(empty CSV file)"


def trim_empty_tail(values: list[str]) -> list[str]:
    trimmed = [value.strip() for value in values]
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return trimmed


def _filesystem_facade():
    from ci2lab.harness.tools import filesystem

    return filesystem
