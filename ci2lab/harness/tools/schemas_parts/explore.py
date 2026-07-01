"""OpenAI function schemas for read-only exploration tools.

Defines :data:`EXPLORE_SCHEMAS`, the schemas for tools that read or search the
workspace without mutating it (read, list, grep, glob, tree, inspect). These
are aggregated into the full tool set by
:mod:`ci2lab.harness.tools.schemas_parts.builtins`.
"""

from __future__ import annotations

from typing import Any

#: OpenAI-compatible function schemas for read-only exploration tools.
EXPLORE_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a whole text/code file and return numbered lines. For office documents prefer read_document. For a known line range of a large file, use inspect_file instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "description": "First line to read (1-based)"},
                    "limit": {"type": "integer", "description": "Max number of lines to read"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": (
                "Read PDF, DOCX, PPTX, XLSX, CSV, Markdown and plain text, "
                "returning format metadata and extracted text."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_quiz_questions",
            "description": (
                "Create multiple-choice test questions from PDF, DOCX, PPTX, XLSX, "
                "CSV, Markdown or plain text. Use this when the user asks for "
                "preguntas tipo test, quiz questions, exam questions or similar. "
                "Ask the user first when question_count or difficulty is missing. "
                "Each generated question has exactly one correct answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Document path to read"},
                    "question_count": {
                        "type": "integer",
                        "description": "Number of questions requested by the user",
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["basic", "medium", "hard"],
                        "description": "Question difficulty: basic/easy, medium or hard",
                    },
                    "options_per_question": {
                        "type": "integer",
                        "description": "Choices per question; default is 4 when omitted",
                    },
                },
                "required": ["path", "question_count", "difficulty"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "List the entries of one directory. For a recursive view use tree.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search file contents by regex across the workspace. Use to find where text or symbols appear.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "glob": {"type": "string"},
                    "ignore_case": {"type": "boolean"},
                    "max_results": {"type": "integer"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files by name pattern (e.g. **/*.py). Use to locate files by name, not by content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_info",
            "description": "Get metadata for a file or directory (size, type) without reading its content.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tree",
            "description": "Show a bounded directory tree (control depth and max_entries). Use to understand project layout cheaply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "depth": {"type": "integer"},
                    "max_entries": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_file",
            "description": "Read a bounded line range of a text file. Cheaper than read_file for large files when you know the range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
]
