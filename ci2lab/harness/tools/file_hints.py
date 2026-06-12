"""Mensajes de ayuda cuando una ruta de archivo no existe."""

from __future__ import annotations

from pathlib import Path


def format_missing_file_error(cwd: str, resolved: Path) -> str:
    base = Path(cwd).resolve()
    message = f"Error: no existe el archivo {resolved}"
    try:
        root_files = sorted(base.glob("*.py"))[:10]
    except OSError:
        root_files = []
    if root_files:
        names = ", ".join(item.name for item in root_files)
        message += f". Archivos .py en la raiz del workspace: {names}"
    message += ". Usa read_file con la ruta exacta antes de editar."
    return message
