"""Human-readable tool summaries used by permission prompts."""

from __future__ import annotations

from typing import Any


def permission_summary(tool_name: str, args: dict[str, Any]) -> str:
    """Short summary for the confirmation dialog.

    Args:
        tool_name: The name of the tool awaiting confirmation.
        args: The tool's invocation arguments.

    Returns:
        A truncated, human-readable summary tailored to ``tool_name`` (falling
        back to a generic ``str(args)`` rendering for unknown tools).
    """
    if tool_name == "bash":
        cmd = args.get("command", "")
        return cmd[:120] + ("..." if len(cmd) > 120 else "")
    if tool_name in ("write_file", "edit_file", "notebook_edit"):
        return str(args.get("path", ""))
    if tool_name == "apply_patch":
        patch = str(args.get("patch", ""))
        return patch[:120] + ("..." if len(patch) > 120 else "")
    if tool_name == "fill_docx_template":
        return f"{args.get('template', '')} → {args.get('output', '')}"
    if tool_name == "web_fetch":
        return str(args.get("url", ""))[:120]
    if tool_name == "ask_user":
        return str(args.get("question", ""))[:120]
    return str(args)[:80]
