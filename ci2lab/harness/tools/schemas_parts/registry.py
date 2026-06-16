"""Tool-name registry."""

from __future__ import annotations

TOOL_NAMES = frozenset({
    "bash",
    "read_file",
    "read_document",
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
    "web_search",
    "notebook_edit",
    "git_status",
    "git_diff",
    "skill",
    "mcp_call",
    "docx_to_pdf",
    "pdf_to_docx",
})


def is_known_tool(name: str) -> bool:
    if name in TOOL_NAMES:
        return True
    return name.startswith("mcp__")
