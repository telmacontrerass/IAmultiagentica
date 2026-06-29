"""Edit Jupyter notebook cells."""

from __future__ import annotations

import json

from ci2lab.harness.tools.paths import resolve_path

_VALID_CELL_TYPES: frozenset[str] = frozenset({"code", "markdown", "raw"})


def notebook_edit(
    cwd: str,
    path: str,
    cell_index: int,
    new_source: str,
    cell_type: str | None = None,
) -> str:
    """Replace the source (and optionally type) of one cell in a notebook.

    Rewrites the cell at ``cell_index`` with ``new_source``; for code cells, any
    existing outputs are cleared. The notebook is written back as JSON.

    Args:
        cwd: The current working directory used to resolve ``path``.
        path: Workspace-relative path to the ``.ipynb`` notebook.
        cell_index: 0-based index of the cell to edit.
        new_source: The new cell source text.
        cell_type: Optional new cell type; one of ``code``, ``markdown`` or
            ``raw``. If ``None`` the existing type is kept.

    Returns:
        A success message naming the edited cell, or an ``"Error: ..."`` message
        if the file/cell is invalid or out of range.
    """
    resolved = resolve_path(path, cwd)
    if not resolved.is_file():
        return f"Error: file does not exist: {resolved}"
    if resolved.suffix.lower() != ".ipynb":
        return f"Error: {resolved} is not a .ipynb notebook"

    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"Error: invalid notebook JSON: {exc}"

    cells = data.get("cells")
    if not isinstance(cells, list):
        return f"Error: notebook has no cells array in {resolved}"

    idx = int(cell_index)
    if idx < 0 or idx >= len(cells):
        return f"Error: cell_index {idx} out of range (0..{len(cells) - 1})"

    cell = cells[idx]
    if not isinstance(cell, dict):
        return f"Error: cell {idx} is not an object"

    if cell_type is not None:
        ctype = str(cell_type).lower()
        if ctype not in _VALID_CELL_TYPES:
            return (
                f"Error: invalid cell_type {ctype!r}; "
                f"use one of: {', '.join(sorted(_VALID_CELL_TYPES))}"
            )
        cell["cell_type"] = ctype

    cell["source"] = _to_source_list(new_source)
    if cell.get("cell_type") == "code" and "outputs" in cell:
        cell["outputs"] = []

    resolved.write_text(
        json.dumps(data, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    preview = new_source.strip().splitlines()[0][:80] if new_source.strip() else "(empty)"
    return f"Edited {resolved} cell {idx}: {preview}"


def _to_source_list(text: str) -> list[str]:
    """Split ``text`` into the newline-terminated line list nbformat expects."""
    if not text:
        return []
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] = lines[-1] + "\n"
    return lines
