"""Human-readable tool summaries used by permission prompts."""

from __future__ import annotations


def permission_summary(tool_name: str, args: dict) -> str:
    """Resumen corto para el diálogo de confirmación."""
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

