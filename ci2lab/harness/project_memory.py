"""Load project memory files from the workspace."""

from __future__ import annotations

from pathlib import Path

MAX_MEMORY_CHARS = 12_000

_MEMORY_CANDIDATES = (
    "CI2LAB.md",
    "AGENTS.md",
    ".ci2lab/CI2LAB.md",
    ".ci2lab/AGENTS.md",
)


def load_project_memory(cwd: str) -> str:
    """
    Load standing project instructions from the workspace root.

    Files are merged in order; later files append if not duplicate-heavy.
    """
    root = Path(cwd).resolve()
    sections: list[str] = []
    total = 0
    for rel in _MEMORY_CANDIDATES:
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not text:
            continue
        header = f"### From `{rel}`"
        block = f"{header}\n\n{text}"
        if total + len(block) > MAX_MEMORY_CHARS:
            remaining = MAX_MEMORY_CHARS - total
            if remaining < 200:
                break
            block = block[:remaining] + "\n... (memory truncated)"
        sections.append(block)
        total += len(block)
        if total >= MAX_MEMORY_CHARS:
            break
    if not sections:
        return ""
    return "## Project memory\n\n" + "\n\n".join(sections)
