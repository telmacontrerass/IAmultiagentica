"""Herramientas de lectura y listado de archivos."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ci2lab.harness.tools.paths import format_size, resolve_path

MAX_READ_LINES = 2000


def read_file(cwd: str, path: str, offset: int = 1, limit: int | None = None) -> str:
    resolved = resolve_path(path, cwd)
    if not resolved.is_file():
        return f"Error: no existe el archivo {resolved}"
    text = resolved.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = max(1, offset)
    end = start + (limit or MAX_READ_LINES) - 1
    slice_lines = lines[start - 1 : end]
    numbered = [f"{i + start:6d}|{line}" for i, line in enumerate(slice_lines)]
    if len(lines) > end:
        numbered.append(f"... ({len(lines) - end} líneas más; usa offset/limit)")
    return "\n".join(numbered) if numbered else "(archivo vacío)"


def ls(cwd: str, path: str = ".") -> str:
    resolved = resolve_path(path or ".", cwd)
    if not resolved.is_dir():
        return f"Error: no es un directorio {resolved}"
    dirs: list[str] = []
    files: list[str] = []
    for entry in sorted(resolved.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            dirs.append(f"  {entry.name}/")
        elif entry.is_file():
            files.append(f"  {entry.name}  ({format_size(entry.stat().st_size)})")
    lines = [f"{resolved}/"]
    lines.extend(dirs)
    lines.extend(files)
    return "\n".join(lines) if len(lines) > 1 else f"{resolved}/ (vacío)"


def glob_search(cwd: str, pattern: str, path: str = ".") -> str:
    base = resolve_path(path or ".", cwd)
    if not base.is_dir():
        return f"Error: base no es directorio {base}"
    matches = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        return f"Sin coincidencias para `{pattern}` en {base}"
    lines = [str(m.relative_to(Path(cwd).resolve())) for m in matches[:100]]
    if len(matches) > 100:
        lines.append(f"... y {len(matches) - 100} más")
    return "\n".join(lines)


def grep_search(
    cwd: str,
    pattern: str,
    path: str = ".",
    glob_pattern: str | None = None,
    ignore_case: bool = False,
    max_results: int = 50,
) -> str:
    base = resolve_path(path or ".", cwd)
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return f"Error: expresión regular inválida: {exc}"

    # Intentar ripgrep si está disponible (más rápido y respeta .gitignore).
    rg_cmd = ["rg", "--line-number", "--no-heading", pattern, str(base)]
    if ignore_case:
        rg_cmd.insert(1, "-i")
    if glob_pattern:
        rg_cmd.extend(["--glob", glob_pattern])
    try:
        proc = subprocess.run(
            rg_cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        if proc.returncode in (0, 1) and proc.stdout.strip():
            lines = proc.stdout.strip().splitlines()[:max_results]
            return "\n".join(lines)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback Python.
    results: list[str] = []
    root = Path(cwd).resolve()
    files = [base] if base.is_file() else base.rglob("*")
    for file_path in files:
        if not file_path.is_file():
            continue
        if glob_pattern and not file_path.match(glob_pattern):
            continue
        try:
            rel = file_path.relative_to(root)
        except ValueError:
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(content.splitlines(), start=1):
            if regex.search(line):
                results.append(f"{rel}:{i}:{line}")
                if len(results) >= max_results:
                    return "\n".join(results)
    return "\n".join(results) if results else f"Sin coincidencias para `{pattern}`"


def write_file(cwd: str, path: str, content: str) -> str:
    resolved = resolve_path(path, cwd)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"Escrito {resolved} ({len(content)} caracteres)"


def edit_file(
    cwd: str,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    resolved = resolve_path(path, cwd)
    if not resolved.is_file():
        return f"Error: no existe {resolved}"
    text = resolved.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        return "Error: old_string no encontrado en el archivo"
    if not replace_all and count > 1:
        return f"Error: old_string aparece {count} veces; usa replace_all o hazlo único"
    new_text = text.replace(old_string, new_string, count if replace_all else 1)
    resolved.write_text(new_text, encoding="utf-8")
    replaced = count if replace_all else 1
    return f"Editado {resolved}: {replaced} reemplazo(s)"


def permission_summary(tool_name: str, args: dict) -> str:
    """Resumen corto para el diálogo de confirmación."""
    if tool_name == "bash":
        cmd = args.get("command", "")
        return cmd[:120] + ("..." if len(cmd) > 120 else "")
    if tool_name in ("write_file", "edit_file"):
        return str(args.get("path", ""))
    return str(args)[:80]
