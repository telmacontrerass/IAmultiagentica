"""OpenAI function schemas for file-editing tools.

Defines :data:`EDIT_SCHEMAS`, the schemas for tools that create or modify files
(write, edit, patch, document conversion, notebook edits). These are aggregated
into the full tool set by :mod:`ci2lab.harness.tools.schemas_parts.builtins`.
"""

from __future__ import annotations

from typing import Any

#: OpenAI-compatible function schemas for file-editing tools.
EDIT_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with plain text. Put the full file text in `content`. Not for .docx — use write_docx instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_docx",
            "description": (
                "Create or overwrite a Word .docx file. Put markdown text in `content`; "
                "pandoc converts it to .docx. Use for reports, letters, translated documents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Output path ending in .docx"},
                    "content": {
                        "type": "string",
                        "description": "Document body as markdown (headings, lists, paragraphs)",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_pptx",
            "description": (
                "Create a real editable PowerPoint .pptx file from structured slides. "
                "Supported slide types: cover, section, bullets, two_columns, table, "
                "quote, closing, metric_cards, comparison, decision."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "output_path": {
                        "type": "string",
                        "description": "Workspace-relative output path ending in .pptx",
                    },
                    "title": {
                        "type": "string",
                        "description": "Presentation title",
                    },
                    "slides": {
                        "type": "array",
                        "description": "Structured slide objects",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "cover",
                                        "section",
                                        "bullets",
                                        "two_columns",
                                        "table",
                                        "quote",
                                        "closing",
                                        "metric_cards",
                                        "comparison",
                                        "decision",
                                    ],
                                }
                            },
                            "required": ["type"],
                        },
                    },
                    "theme": {
                        "type": "object",
                        "description": "Optional deterministic visual theme",
                        "additionalProperties": True,
                        "properties": {
                            "font_family": {"type": "string"},
                            "title_font_size": {"type": "integer"},
                            "body_font_size": {"type": "integer"},
                            "primary_color": {"type": "string"},
                            "secondary_color": {"type": "string"},
                            "background_color": {"type": "string"},
                            "footer_text": {"type": "string"},
                            "slide_number": {"type": "boolean"},
                        },
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Set true to replace an existing .pptx",
                    },
                },
                "required": ["output_path", "title", "slides"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit an existing file by exact text replacement. `old_string` must match the current text exactly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Apply a unified diff patch to one or more text files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": "Unified diff text (git diff style)",
                    }
                },
                "required": ["patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill_docx_template",
            "description": "Fill {{field}} placeholders in a DOCX template and save a DOCX output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "template": {"type": "string"},
                    "output": {"type": "string"},
                    "fields": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["template", "output", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docx_to_pdf",
            "description": (
                "Convert a Word .docx file to PDF using pandoc. "
                "Requires pandoc on PATH and a PDF engine (e.g. wkhtmltopdf, weasyprint)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Path to the source .docx file",
                    },
                    "output": {
                        "type": "string",
                        "description": "Path for the output .pdf file",
                    },
                },
                "required": ["source", "output"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pdf_to_docx",
            "description": (
                "Convert a PDF file to a Word .docx file using pdf2docx. "
                "Preserves layout, images, and tables. Requires `pdf2docx` installed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Path to the source .pdf file",
                    },
                    "output": {
                        "type": "string",
                        "description": "Path for the output .docx file",
                    },
                },
                "required": ["source", "output"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notebook_edit",
            "description": "Edit one cell in a Jupyter .ipynb notebook.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "cell_index": {
                        "type": "integer",
                        "description": "Zero-based cell index",
                    },
                    "new_source": {"type": "string"},
                    "cell_type": {
                        "type": "string",
                        "description": "code, markdown, or raw",
                    },
                },
                "required": ["path", "cell_index", "new_source"],
            },
        },
    },
]
