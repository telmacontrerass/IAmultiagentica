"""Canonical registry of built-in tool names.

``TOOL_NAMES`` is the authoritative set of tools the harness recognises. It must
stay in sync with the three other places a tool is declared — its JSON schema
(``schemas_parts``), its dispatch entry (``dispatch.DISPATCH``) and its
capability category (``capabilities``). ``tests/test_tool_registry_consistency``
fails fast if any of these drift apart.
"""

from __future__ import annotations

TOOL_NAMES: frozenset[str] = frozenset(
    {
        "bash",
        "calc",
        "symcalc",
        "read_file",
        "read_document",
        "create_quiz_questions",
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
        "yard",
        "mcp_call",
        "analyze_image",
        "extract_visual_document",
        "docx_to_pdf",
        "pdf_to_docx",
        "delegate",
    }
)


def is_known_tool(name: str) -> bool:
    """Return whether ``name`` is a built-in tool or an MCP tool.

    Args:
        name: The canonical tool name to check.

    Returns:
        ``True`` for any name in :data:`TOOL_NAMES` or any dynamic MCP tool
        (``mcp__*`` prefix); ``False`` otherwise.
    """
    if name in TOOL_NAMES:
        return True
    return name.startswith("mcp__")
