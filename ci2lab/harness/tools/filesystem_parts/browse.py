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
    """Read a text/document file and return numbered lines.

    Args:
        cwd: The workspace root used to resolve and bound ``path``.
        path: The file to read, absolute or relative to ``cwd``.
        offset: 1-based line number to start reading from.
        limit: Maximum number of lines to return, or ``None`` for the default.
        security_engine: Identifier of the security engine to consult.

    Returns:
        The numbered file contents, or an ``"Error: ..."`` message when the path
        is invalid, missing, or blocked by the sensitive-file policy.
    """
    resolved, err = resolve_for_access(path, cwd, security_engine=security_engine)
    if err:
        return err
    assert resolved is not None
    if not resolved.is_file():
        return f"Error: file does not exist: {resolved}"
    if check_sensitive(resolved, cwd, security_engine=security_engine):
        return secret_file_block_message()
    text = extract_document_text(resolved, include_metadata=False)
    if text.startswith("Error:"):
        return text
    return numbered_lines(text, offset=offset, limit=limit)


def read_document(cwd: str, path: str) -> str:
    """Read a document-like file and return structured extracted text.

    Args:
        cwd: The workspace root used to resolve and bound ``path``.
        path: The document to read, absolute or relative to ``cwd``.

    Returns:
        The extracted text with metadata, or an ``"Error: ..."`` message when
        the path is invalid, missing, or blocked by the sensitive-file policy.
    """
    resolved, err = resolve_or_error(path, cwd)
    if err:
        return err
    assert resolved is not None
    if not resolved.is_file():
        return f"Error: file does not exist: {resolved}"
    if is_sensitive_path(resolved):
        return secret_file_block_message()
    return extract_document_text(resolved, include_metadata=True)


def ls(cwd: str, path: str = ".") -> str:
    """List the immediate, non-hidden contents of a directory.

    Directories are listed first (with a trailing ``/``), then files annotated
    with their human-readable size. Entries whose name starts with ``.`` are
    omitted.

    Args:
        cwd: The workspace root used to resolve and bound ``path``.
        path: The directory to list, absolute or relative to ``cwd``.

    Returns:
        A newline-joined listing rooted at the resolved directory, or an
        ``"Error: ..."`` message when the path is invalid or not a directory.
    """
    resolved, err = resolve_or_error(path or ".", cwd)
    if err:
        return err
    assert resolved is not None
    if not resolved.is_dir():
        return f"Error: not a directory: {resolved}"
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
    return "\n".join(lines) if len(lines) > 1 else f"{resolved}/ (empty)"


# Dependency/build directories that flood pattern searches with noise and are
# almost never what the user means. Skipped unless the pattern names them.
_GLOB_NOISE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "site-packages",
        ".tox",
        ".idea",
        ".vscode",
        "dist",
        "build",
        ".eggs",
    }
)


def glob_search(cwd: str, pattern: str, path: str = ".") -> str:
    """Find files matching a glob ``pattern`` beneath a base directory.

    Results are sorted most-recently-modified first and capped at 100 entries.
    Dependency/build directories in :data:`_GLOB_NOISE_DIRS` are skipped unless
    the pattern itself names one of them.

    Args:
        cwd: The workspace root used to resolve paths and compute relatives.
        pattern: A glob pattern (e.g. ``**/*.py``) evaluated against ``base``.
        path: The base directory to search, absolute or relative to ``cwd``.

    Returns:
        A newline-joined list of matching paths relative to ``cwd``, a
        no-matches notice, or an ``"Error: ..."`` message for an invalid base.
    """
    base, err = resolve_or_error(path or ".", cwd)
    if err:
        return err
    assert base is not None
    if not base.is_dir():
        return f"Error: base is not a directory: {base}"
    pattern_names_noise = any(part in _GLOB_NOISE_DIRS for part in pattern.split("/"))
    matches = [
        match
        for match in base.glob(pattern)
        if pattern_names_noise or not any(part in _GLOB_NOISE_DIRS for part in match.parts)
    ]
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        return f"No matches for `{pattern}` in {base}"
    lines = [str(m.relative_to(Path(cwd).resolve())) for m in matches[:100]]
    if len(matches) > 100:
        lines.append(f"... and {len(matches) - 100} more")
    return "\n".join(lines)


def grep_search(
    cwd: str,
    pattern: str,
    path: str = ".",
    glob_pattern: str | None = None,
    ignore_case: bool = False,
    max_results: int = 50,
) -> str:
    """Search file contents for a regex ``pattern`` and report matching lines.

    Sensitive files are skipped and counted in a trailing notice. If ``pattern``
    is not a valid regex it is searched as literal text and a note is prepended.

    Args:
        cwd: The workspace root used to resolve paths and compute relatives.
        pattern: A regular expression (or literal text on regex-compile failure).
        path: The file or directory to search, absolute or relative to ``cwd``.
        glob_pattern: Optional glob to restrict which files are scanned.
        ignore_case: When ``True``, match case-insensitively.
        max_results: Maximum number of matching lines to return.

    Returns:
        ``path:line:text`` matches joined by newlines (optionally with fallback
        and skip notices), a no-matches notice, or an ``"Error: ..."`` message.
    """
    base, err = resolve_or_error(path or ".", cwd)
    if err:
        return err
    assert base is not None
    flags = re.IGNORECASE if ignore_case else 0
    fallback_note = ""
    try:
        regex = re.compile(pattern, flags)
    except re.error:
        # Glob-style patterns (`**/*.docx`) or ones with stray metacharacters are
        # not valid regexes. Instead of failing, we search for the text literally.
        # To locate files by name, `glob` is preferable to `grep`.
        regex = re.compile(re.escape(pattern), flags)
        fallback_note = (
            f"(note: `{pattern}` is not a valid regex; searched as literal "
            "text. To find files by name use the `glob` tool.)\n"
        )

    if base.is_file():
        if is_sensitive_path(base, workspace=cwd):
            return secret_file_block_message()
        return fallback_note + grep_single_file(
            base, root=Path(cwd).resolve(), regex=regex, max_results=max_results
        )

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
        return fallback_note + (f"{body}\n{notice}" if notice else body)
    if skipped:
        notice = grep_skip_notice(skipped)
        return fallback_note + f"No matches for `{pattern}`\n{notice}"
    return fallback_note + f"No matches for `{pattern}`"


def grep_single_file(
    file_path: Path,
    *,
    root: Path,
    regex: re.Pattern[str],
    max_results: int,
) -> str:
    """Search a single file for ``regex`` and format matching lines.

    Args:
        file_path: The file to scan.
        root: Root used to render paths relative in the output.
        regex: The compiled pattern to match against each line.
        max_results: Maximum number of matching lines to return.

    Returns:
        ``rel:line:text`` matches joined by newlines, or a no-matches notice
        when nothing matches or the file cannot be read as text.
    """
    results: list[str] = []
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        rel = file_path
    try:
        content = extract_document_text(file_path, include_metadata=False)
    except OSError:
        return f"No matches for `{regex.pattern}`"
    if content.startswith("Error:"):
        return f"No matches for `{regex.pattern}`"
    for i, line in enumerate(content.splitlines(), start=1):
        if regex.search(line):
            results.append(f"{rel}:{i}:{line}")
            if len(results) >= max_results:
                break
    return "\n".join(results) if results else f"No matches for `{regex.pattern}`"


def grep_scan_tree(
    base: Path,
    *,
    root: Path,
    regex: re.Pattern[str],
    glob_pattern: str | None,
    max_results: int,
) -> tuple[list[str], int]:
    """Recursively search a directory tree for ``regex`` matches.

    Args:
        base: The directory to walk recursively.
        root: Root used to render paths relative in the output.
        regex: The compiled pattern to match against each line.
        glob_pattern: Optional glob restricting which files are scanned.
        max_results: Maximum number of matching lines to collect.

    Returns:
        A ``(results, skipped)`` pair: the formatted ``rel:line:text`` matches
        and the count of sensitive files skipped by policy.
    """
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
