"""Ensamblado del system prompt del arnés."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from ci2lab.contracts.types import ModelSelection, ToolMode

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

    tool_mode: ToolMode = selection.tool_mode
    if tool_mode == "fenced" or not selection.supports_tools:
        parts.append(_read("fenced_tools.md"))

    return "\n\n".join(parts)
