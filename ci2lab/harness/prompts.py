"""Ensamblado del system prompt del arnés."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from ci2lab.contracts.types import ModelSelection, ToolMode
from ci2lab.harness.mcp.session import get_mcp_manager
from ci2lab.harness.project_memory import load_project_memory
from ci2lab.harness.skills.loader import format_skill_catalog, load_skills, skills_for_model

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _read(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def build_system_prompt(
    selection: ModelSelection,
    cwd: str,
) -> str:
    parts = [_read("system.md")]

    parts.append(
        f"\n## Entorno\n"
        f"- Directorio de trabajo: {cwd}\n"
        f"- Fecha: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"- Modelo: {selection.display_name} ({selection.ollama_tag})\n"
        f"- SO: {os.name}"
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

    mcp_status = get_mcp_manager(cwd, connect=True).format_status()
    if mcp_status:
        parts.append(mcp_status)

    tool_mode: ToolMode = selection.tool_mode
    if tool_mode == "fenced" or not selection.supports_tools:
        parts.append(_read("fenced_tools.md"))

    return "\n\n".join(parts)
