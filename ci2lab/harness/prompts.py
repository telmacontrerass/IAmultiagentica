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

_NATIVE_OMITTED_SECTIONS = {
    "## Tools",
    "## Choosing the right tool",
    "## Tool arguments (use these exact names)",
    "## Calling tools",
}


def _read(name: str) -> str:
    """Read and strip a prompt fragment from the bundled ``prompts`` directory.

    Args:
        name: File name of the prompt fragment (relative to ``_PROMPTS_DIR``).

    Returns:
        The fragment's text content with leading/trailing whitespace removed.
    """
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def _base_system_prompt(tool_mode: ToolMode) -> str:
    """Return the base prompt without duplicating API-provided native schemas."""
    text = _read("system.md")
    if tool_mode != "native":
        return text
    kept: list[str] = []
    omit = False
    for line in text.splitlines():
        if line.startswith("## "):
            omit = line.strip() in _NATIVE_OMITTED_SECTIONS
        if not omit:
            kept.append(line)
    return "\n".join(kept).strip()


def build_system_prompt(
    selection: ModelSelection,
    cwd: str,
    *,
    config: object | None = None,
) -> str:
    """Assemble the full system prompt for a harness run.

    Combines the base system prompt with environment details, optional
    OS-specific guidance, project memory, the skill catalog, MCP server status
    and, when the model lacks native tool support, fenced-tool instructions.
    When the run configuration disables the write tools, a read-only notice is
    included so the model plans around that limit instead of attempting calls
    the executor is guaranteed to block.

    Args:
        selection: Resolved model selection driving display name, tool mode and
            tool-support capabilities.
        cwd: Absolute working directory used to load project memory, skills and
            MCP status, and reported back in the environment section.
        config: Optional run configuration; only ``write_tools_enabled`` is
            consulted. Accepts any object exposing that attribute (typically
            :class:`~ci2lab.harness.types.AgentConfig`).

    Returns:
        The complete system prompt as a single newline-joined string.
    """
    tool_mode: ToolMode = selection.tool_mode
    parts = [_base_system_prompt(tool_mode)]

    if config is not None and not getattr(config, "write_tools_enabled", True):
        parts.append(
            "## Read-only session\n\n"
            "File creation and modification are DISABLED for this session: "
            "`write_file`, `edit_file`, `apply_patch`, and the document writers "
            "will not run. Do not attempt them and do not work around the limit "
            "through shell redirection. Answer with the read-only tools "
            "(`ls`, `tree`, `glob`, `grep`, `read_file`, `inspect_file`, "
            "`read_document`) and by running commands that observe rather than "
            "change the workspace."
        )

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

    if tool_mode == "fenced" or not selection.supports_tools:
        parts.append(_read("fenced_tools.md"))

    return "\n\n".join(parts)
