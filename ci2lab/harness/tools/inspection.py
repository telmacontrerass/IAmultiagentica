"""Low-risk inspection tools (read-only, no execution)."""

from __future__ import annotations

from pathlib import Path

from ci2lab.harness.tools.filesystem import _numbered_lines, _resolve_or_error
from ci2lab.harness.tools.paths import format_size, workspace_root
from ci2lab.harness.tools.secret_files import is_sensitive_path, secret_file_block_message

#: Directory names skipped when walking a tree.
SKIPPED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
    }
)

#: Files larger than this (in bytes) are not line-counted.
MAX_LINE_COUNT_BYTES = 512_000
#: Hard cap on the number of lines returned by :func:`inspect_file`.
MAX_INSPECT_LINES = 120
#: Number of leading bytes sampled to detect binary content.
TEXT_PROBE_BYTES = 8192
#: Default recursion depth for :func:`tree`.
DEFAULT_TREE_DEPTH = 2
#: Default maximum number of entries listed by :func:`tree`.
DEFAULT_TREE_MAX_ENTRIES = 200


def _relative_path(path: Path, root: Path) -> str:
    """Return ``path`` relative to ``root`` (posix form), or its own posix form."""
    try:
        rel = path.relative_to(root)
        return "." if rel == Path(".") else rel.as_posix()
    except ValueError:
        return path.as_posix()


def _approx_line_count(path: Path) -> int | None:
    """Return an approximate line count, or ``None`` if too large/binary/unreadable."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > MAX_LINE_COUNT_BYTES:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:TEXT_PROBE_BYTES]:
        return None
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def _looks_binary(path: Path) -> bool:
    """Return ``True`` if ``path`` appears binary (contains a NUL byte or is unreadable)."""
    try:
        sample = path.read_bytes()[:TEXT_PROBE_BYTES]
    except OSError:
        return True
    return b"\x00" in sample


def file_info(cwd: str, path: str) -> str:
    """Report metadata about ``path`` (existence, type, size, line count).

    Args:
        cwd: Workspace root used to resolve and scope ``path``.
        path: The path to inspect, relative to the workspace.

    Returns:
        A newline-joined block of metadata fields, or an error string if the
        path cannot be resolved within the workspace.
    """
    resolved, err = _resolve_or_error(path, cwd)
    if err:
        return err
    assert resolved is not None
    root = workspace_root(cwd)
    rel = _relative_path(resolved, root)
    sensitive = is_sensitive_path(resolved, workspace=cwd)

    lines = [
        f"exists: {'yes' if resolved.exists() else 'no'}",
        f"path: {rel}",
        "in_workspace: yes",
        f"sensitive: {'yes' if sensitive else 'no'}",
    ]
    if not resolved.exists():
        return "\n".join(lines)

    if resolved.is_dir():
        lines.append("type: dir")
        return "\n".join(lines)

    if resolved.is_file():
        lines.append("type: file")
        lines.append(f"extension: {resolved.suffix or '(none)'}")
        try:
            lines.append(f"size: {format_size(resolved.stat().st_size)}")
        except OSError:
            lines.append("size: (desconocido)")
        if not sensitive:
            approx = _approx_line_count(resolved)
            if approx is not None:
                lines.append(f"approx_lines: {approx}")
        return "\n".join(lines)

    lines.append("type: other")
    return "\n".join(lines)


def tree(
    cwd: str,
    path: str = ".",
    depth: int = DEFAULT_TREE_DEPTH,
    max_entries: int = DEFAULT_TREE_MAX_ENTRIES,
) -> str:
    """Render a depth-limited directory tree, skipping noise and sensitive files.

    Args:
        cwd: Workspace root used to resolve and scope ``path``.
        path: Directory to walk, relative to the workspace.
        depth: Maximum recursion depth (clamped at ``>= 0``).
        max_entries: Maximum entries to emit (clamped between 1 and 1000).

    Returns:
        A newline-joined tree listing, or an error string if ``path`` is not a
        directory within the workspace.
    """
    resolved, err = _resolve_or_error(path or ".", cwd)
    if err:
        return err
    assert resolved is not None
    if not resolved.is_dir():
        return f"Error: not a directory: {resolved}"

    root = workspace_root(cwd)
    depth = max(0, depth)
    max_entries = max(1, min(max_entries, 1000))
    rel_root = _relative_path(resolved, root)
    header = f"{rel_root}/" if rel_root != "." else "./"

    lines: list[str] = [header]
    count = 0
    truncated = False
    skipped_sensitive = 0

    def append(line: str) -> bool:
        """Append ``line`` unless the entry budget is exhausted; track truncation."""
        nonlocal count, truncated
        if count >= max_entries:
            truncated = True
            return False
        lines.append(line)
        count += 1
        return True

    def walk(dir_path: Path, prefix: str, current_depth: int) -> None:
        """Recursively emit entries under ``dir_path`` up to the depth/entry limits."""
        nonlocal truncated, skipped_sensitive
        if truncated or current_depth > depth:
            return
        try:
            entries = sorted(
                dir_path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            return
        for entry in entries:
            if truncated:
                return
            if entry.name in SKIPPED_DIR_NAMES:
                continue
            if is_sensitive_path(entry, workspace=cwd):
                skipped_sensitive += 1
                if not append(f"{prefix}[sensitive omitted] {entry.name}"):
                    return
                continue
            if entry.is_dir():
                if not append(f"{prefix}{entry.name}/"):
                    return
                walk(entry, prefix + "  ", current_depth + 1)
            elif entry.is_file():
                if not append(f"{prefix}{entry.name}"):
                    return

    walk(resolved, "  ", 1)
    if truncated:
        lines.append(f"... (output truncated; max_entries={max_entries})")
    if skipped_sensitive:
        lines.append(f"(policy: {skipped_sensitive} sensitive entry(ies) omitted without content)")
    return "\n".join(lines)


def inspect_file(
    cwd: str,
    path: str,
    start: int = 1,
    end: int | None = None,
    max_lines: int = MAX_INSPECT_LINES,
) -> str:
    """Return a numbered slice of a text file's lines, with a remainder note.

    Args:
        cwd: Workspace root used to resolve and scope ``path``.
        path: The text file to inspect, relative to the workspace.
        start: 1-based line number to start from (clamped at ``>= 1``).
        end: Optional 1-based inclusive end line; ``None`` reads up to the cap.
        max_lines: Maximum number of lines to emit (clamped at
            :data:`MAX_INSPECT_LINES`).

    Returns:
        The numbered lines plus an optional "more lines" footer, or an error
        string for a missing/binary/sensitive file or an invalid range.
    """
    resolved, err = _resolve_or_error(path, cwd)
    if err:
        return err
    assert resolved is not None
    if not resolved.exists():
        return f"Error: file does not exist: {resolved}"
    if not resolved.is_file():
        return f"Error: not a file {resolved}"
    if is_sensitive_path(resolved, workspace=cwd):
        return secret_file_block_message()
    if _looks_binary(resolved):
        return (
            "Error: the file looks binary; inspect_file only supports text. "
            "Use file_info for metadata."
        )

    cap = max(1, min(max_lines, MAX_INSPECT_LINES))
    line_start = max(1, start)
    if end is not None and end < line_start:
        return "Error: end must be >= start"
    if end is None:
        limit = cap
    else:
        limit = min(cap, end - line_start + 1)

    text = resolved.read_text(encoding="utf-8", errors="replace")
    total = len(text.splitlines())
    body = _numbered_lines(text, offset=line_start, limit=limit)
    if end is not None and end < total:
        body += f"\n... ({total - end} more lines; total {total})"
    elif line_start + limit - 1 < total:
        body += f"\n... ({total - (line_start + limit - 1)} more lines; total {total})"
    return body
