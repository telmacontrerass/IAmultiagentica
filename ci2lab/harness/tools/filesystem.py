"""File reading, searching and editing tools."""

from __future__ import annotations

from ci2lab.harness.tools.filesystem_parts.access import (
    check_sensitive as _check_sensitive,
)
from ci2lab.harness.tools.filesystem_parts.access import (
    resolve_for_access as _resolve_for_access,
)
from ci2lab.harness.tools.filesystem_parts.access import (
    resolve_or_error as _resolve_or_error,
)
from ci2lab.harness.tools.filesystem_parts.browse import (
    glob_search,
    grep_search,
    ls,
    read_document,
    read_file,
)
from ci2lab.harness.tools.filesystem_parts.browse import (
    grep_scan_tree as _grep_scan_tree,
)
from ci2lab.harness.tools.filesystem_parts.browse import (
    grep_single_file as _grep_single_file,
)
from ci2lab.harness.tools.filesystem_parts.documents import (
    MAX_DOCUMENT_CHARS,
    MAX_PDF_PAGES,
    MAX_PRESENTATION_SLIDES,
    MAX_READ_LINES,
    MAX_SPREADSHEET_COLS,
    MAX_SPREADSHEET_ROWS,
    OFFICE_DOCUMENT_SUFFIXES,
    SUPPORTED_DOCUMENT_SUFFIXES,
    TEXT_DOCUMENT_SUFFIXES,
    extract_csv_text,
    extract_document_text,
    extract_docx_text,
    extract_pdf_text,
    extract_pptx_text,
    extract_xlsx_text,
)
from ci2lab.harness.tools.filesystem_parts.documents import (
    numbered_lines as _numbered_lines,
)
from ci2lab.harness.tools.filesystem_parts.documents import (
    pdf_section_count as _pdf_section_count,
)
from ci2lab.harness.tools.filesystem_parts.documents import (
    trim_empty_tail as _trim_empty_tail,
)
from ci2lab.harness.tools.filesystem_parts.documents import (
    truncate_document_text as _truncate_document_text,
)
from ci2lab.harness.tools.filesystem_parts.mutate import edit_file, write_file
from ci2lab.harness.tools.filesystem_parts.permissions import permission_summary

__all__ = [
    "MAX_DOCUMENT_CHARS",
    "MAX_PDF_PAGES",
    "MAX_PRESENTATION_SLIDES",
    "MAX_READ_LINES",
    "MAX_SPREADSHEET_COLS",
    "MAX_SPREADSHEET_ROWS",
    "OFFICE_DOCUMENT_SUFFIXES",
    "SUPPORTED_DOCUMENT_SUFFIXES",
    "TEXT_DOCUMENT_SUFFIXES",
    "edit_file",
    "extract_csv_text",
    "extract_document_text",
    "extract_docx_text",
    "extract_pdf_text",
    "extract_pptx_text",
    "extract_xlsx_text",
    "glob_search",
    "grep_search",
    "ls",
    "permission_summary",
    "read_document",
    "read_file",
    "write_file",
]
