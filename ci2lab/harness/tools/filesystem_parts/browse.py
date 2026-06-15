"""Read, list, glob and grep filesystem tools."""

from __future__ import annotations

import re
from pathlib import Path

from ci2lab.harness.tools.filesystem_parts.access import (
    check_sensitive,
    resolve_for_access,
    resolve_or_error,
)
from ci2lab.harness.tools.filesystem_parts.documents import (
    extract_document_text,
    numbered_lines,
)
from ci2lab.harness.tools.paths import format_size
from ci2lab.harness.tools.secret_files import (
    grep_skip_notice,
    is_sensitive_path,
    secret_file_block_message,
)


def read_file(
    cwd: str,
    path: str,
    offset: int = 1,
    limit: int | None = None,
    *,
    security_engine: str = "ci2lab",
) -> str:
    resolved, err = resolve_for_access(path, cwd, security_engine=security_engine)
    if err:
        return err
    assert resolved is not None
    if not resolved.is_file():
        return f"Error: no existe el archivo {resolved}"
    if check_sensitive(resolved, cwd, security_engine=security_engine):
        return secret_file_block_message()
    text = extract_document_text(resolved, include_metadata=False)
    if text.startswith("Error:"):
        return text
    return numbered_lines(text, offset=offset, limit=limit)


def read_document(cwd: str, path: str) -> str:
    """Read a document-like file and return structured extracted text."""
    resolved, err = resolve_or_error(path, cwd)
    if err:
        return err
    assert resolved is not None
    if not resolved.is_file():
        return f"Error: no existe el archivo {resolved}"
    if is_sensitive_path(resolved):
        return secret_file_block_message()
    return extract_document_text(resolved, include_metadata=True)


def ls(cwd: str, path: str = ".") -> str:
    resolved, err = resolve_or_error(path or ".", cwd)
    if err:
        return err
    assert resolved is not None
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
    base, err = resolve_or_error(path or ".", cwd)
    if err:
        return err
    assert base is not None
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
    base, err = resolve_or_error(path or ".", cwd)
    if err:
        return err
    assert base is not None
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return f"Error: expresión regular inválida: {exc}"

    if base.is_file():
        if is_sensitive_path(base, workspace=cwd):
            return secret_file_block_message()
        return grep_single_file(base, root=Path(cwd).resolve(), regex=regex, max_results=max_results)

    results, skipped = grep_scan_tree(
        base,
        root=Path(cwd).resolve(),
        regex=regex,
        glob_pattern=glob_pattern,
        max_results=max_results,
    )
    if results:
        body = "\n".join(results)
        notice = grep_skip_notice(skipped)
        return f"{body}\n{notice}" if notice else body
    if skipped:
        notice = grep_skip_notice(skipped)
        return f"Sin coincidencias para `{pattern}`\n{notice}"
    return f"Sin coincidencias para `{pattern}`"


def grep_single_file(
    file_path: Path,
    *,
    root: Path,
    regex: re.Pattern[str],
    max_results: int,
) -> str:
    results: list[str] = []
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        rel = file_path
    try:
        content = extract_document_text(file_path, include_metadata=False)
    except OSError:
        return f"Sin coincidencias para `{regex.pattern}`"
    if content.startswith("Error:"):
        return f"Sin coincidencias para `{regex.pattern}`"
    for i, line in enumerate(content.splitlines(), start=1):
        if regex.search(line):
            results.append(f"{rel}:{i}:{line}")
            if len(results) >= max_results:
                break
    return "\n".join(results) if results else f"Sin coincidencias para `{regex.pattern}`"


def grep_scan_tree(
    base: Path,
    *,
    root: Path,
    regex: re.Pattern[str],
    glob_pattern: str | None,
    max_results: int,
) -> tuple[list[str], int]:
    results: list[str] = []
    skipped = 0
    for file_path in base.rglob("*"):
        if not file_path.is_file():
            continue
        if glob_pattern and not file_path.match(glob_pattern):
            continue
        if is_sensitive_path(file_path, workspace=root):
            skipped += 1
            continue
        try:
            rel = file_path.relative_to(root)
        except ValueError:
            continue
        try:
            content = extract_document_text(file_path, include_metadata=False)
        except OSError:
            continue
        if content.startswith("Error:"):
            continue
        for i, line in enumerate(content.splitlines(), start=1):
            if regex.search(line):
                results.append(f"{rel}:{i}:{line}")
                if len(results) >= max_results:
                    return results, skipped
    return results, skipped

