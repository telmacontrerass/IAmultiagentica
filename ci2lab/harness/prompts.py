"""Assembly of the harness system prompt."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from ci2lab.contracts.types import ModelSelection, ToolMode
from ci2lab.harness.mcp.session import get_mcp_manager
from ci2lab.harness.project_memory import load_project_memory
from ci2lab.harness.skills.loader import format_skill_catalog, load_skills, skills_for_model
from ci2lab.harness.yard.loader import load_components

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _read(name: str) -> str:
    """Read and strip a prompt fragment from the bundled ``prompts`` directory.

    Args:
        name: File name of the prompt fragment (relative to ``_PROMPTS_DIR``).

    Returns:
        The fragment's text content with leading/trailing whitespace removed.
    """
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def build_system_prompt(
    selection: ModelSelection,
    cwd: str,
) -> str:
    """Assemble the full system prompt for a harness run.

    Combines the base system prompt with environment details, optional
    OS-specific guidance, project memory, the skill catalog, MCP server status
    and, when the model lacks native tool support, fenced-tool instructions.

    Args:
        selection: Resolved model selection driving display name, tool mode and
            tool-support capabilities.
        cwd: Absolute working directory used to load project memory, skills and
            MCP status, and reported back in the environment section.

    Returns:
        The complete system prompt as a single newline-joined string.
    """
    parts = [_read("system.md")]

    parts.append(
        f"\n## Environment\n"
        f"- Working directory: {cwd}\n"
        f"- Date: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"- Model: {selection.display_name} ({selection.ollama_tag})\n"
        f"- OS: {os.name}"
    )
    if os.name == "nt":
        parts.append(
            "## Windows shell\n\n"
            "- To explore the repo, prefer `tree`, `ls`, `glob`, and `grep`.\n"
            "- Do not use `bash` for Unix listing commands like `ls -l`.\n"
            "- If you need a shell on Windows, use a command that is valid on Windows."
        )

    memory = load_project_memory(cwd)
    if memory:
        parts.append(memory)

    catalog_skills = skills_for_model(load_skills(cwd))
    catalog = format_skill_catalog(catalog_skills)
    if catalog:
        parts.append(
            "## Skills\n\n"
            "Invoke a skill with the `skill` tool when its workflow fits the task. "
            "Skills inject step-by-step instructions; they are not separate executables.\n\n"
            + catalog
        )

    yard_components = load_components(cwd)
    if yard_components:
        parts.append(
            "## Yard\n\n"
            f"A catalog of {len(yard_components)} reusable, runnable code components is "
            'available through the `yard` tool. Call `yard` with action="list" to browse '
            'them (optionally narrow with `query`), action="describe" to see one '
            'component\'s entrypoints and parameters, and action="run" to execute one. '
            "Prefer a matching component over re-implementing it."
        )

    mcp_status = get_mcp_manager(cwd, connect=True).format_status()
    if mcp_status:
        parts.append(mcp_status)

    tool_mode: ToolMode = selection.tool_mode
    if tool_mode == "fenced" or not selection.supports_tools:
        parts.append(_read("fenced_tools.md"))

    return "\n\n".join(parts)
