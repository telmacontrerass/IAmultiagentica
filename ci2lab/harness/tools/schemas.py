"""OpenAI function schemas and tool name registry."""

from __future__ import annotations

from typing import Any

from ci2lab.harness.types import AgentConfig

TOOL_NAMES = frozenset({
    "bash",
    "read_document",
    "read_file",
    "ls",
    "grep",
    "glob",
    "write_file",
    "write_docx",
    "edit_file",
    "apply_patch",
    "fill_docx_template",
    "file_info",
    "tree",
    "inspect_file",
    "todo_write",
    "ask_user",
    "web_fetch",
    "notebook_edit",
    "git_status",
    "git_diff",
    "skill",
    "mcp_call",
})


def is_known_tool(name: str) -> bool:
    if name in TOOL_NAMES:
        return True
    return name.startswith("mcp__")

# Schemas compatibles con OpenAI function calling (extraídos/adaptados de Odysseus).
FUNCTION_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command (build, tests, installs, running scripts). Asks for confirmation. Prefer read-only tools for exploring; use bash only when no read-only tool fits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
    },
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
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": (
                "Replace the workspace task list (.ci2lab/todos.json) for multi-step work. "
                "Each item needs content and status (pending, in_progress, completed, cancelled)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {"type": "string"},
                            },
                            "required": ["content"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Ask the user a question when you need a decision. "
                "Blocks until the user answers in the terminal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional numbered choices",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch a public http(s) URL and return text (HTML is stripped). "
                "Use for docs or reference pages, not for secrets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Max characters to return (default 80000)",
                    },
                },
                "required": ["url"],
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
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show short git status for the workspace or a path inside it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to workspace (default .)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show git diff for the workspace or a specific file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "staged": {
                        "type": "boolean",
                        "description": "If true, show staged changes only",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill",
            "description": (
                "Load a workspace skill workflow by name. Returns instructions to follow "
                "using the listed tools. Use when a skill in the catalog matches the task."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Skill name from the Skills catalog",
                    },
                    "args": {
                        "type": "string",
                        "description": "Optional free-text arguments for the skill",
                    },
                },
                "required": ["skill_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_call",
            "description": (
                "Call a tool on a connected MCP server by server name and tool name. "
                "Prefer dedicated mcp__* tools when listed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string"},
                    "tool": {"type": "string"},
                    "arguments": {
                        "type": "object",
                        "description": "Tool arguments object",
                    },
                },
                "required": ["server", "tool"],
            },
        },
    },
]


def get_function_schemas(config: AgentConfig | None = None) -> list[dict[str, Any]]:
    """Built-in tools plus dynamic MCP tools, optionally filtered by an active skill."""
    schemas: list[dict[str, Any]] = list(FUNCTION_SCHEMAS)
    if config is not None:
        from ci2lab.harness.mcp.session import get_mcp_manager

        mgr = get_mcp_manager(config.cwd, connect=True)
        schemas.extend(mgr.build_function_schemas())
    if config is not None and config.skill_allowed_tools is not None:
        allowed = config.skill_allowed_tools
        schemas = [
            schema
            for schema in schemas
            if schema.get("function", {}).get("name") in allowed
        ]
    return schemas
