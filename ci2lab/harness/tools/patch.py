"""Apply patches in unified diff format (git diff style)."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from ci2lab.harness.tools.paths import PathViolationError, resolve_path
from ci2lab.harness.tools.secret_files import is_sensitive_path, secret_file_block_message

_HUNK_HEADER: re.Pattern[str] = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_NO_NL: str = "\\ No newline at end of file"


@dataclass
class Hunk:
    """A single unified-diff hunk: its header range and body lines.

    Attributes:
        old_start: 1-based start line of the hunk in the original file.
        old_count: Number of original lines covered by the hunk.
        new_start: 1-based start line of the hunk in the new file.
        new_count: Number of new lines covered by the hunk.
        lines: Body lines, each prefixed with ``' '``, ``'-'`` or ``'+'``.
    """

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FilePatch:
    """The parsed patch for one file: its path, hunks and create/delete flags.

    Attributes:
        path: Workspace-relative path of the patched file.
        hunks: Ordered list of hunks to apply to the file.
        is_new_file: True if the patch creates the file (``---`` is /dev/null).
        is_delete: True if the patch deletes the file (``+++`` is /dev/null).
    """

    path: str
    hunks: list[Hunk]
    is_new_file: bool = False
    is_delete: bool = False


@dataclass
class PatchPlan:
    """A resolved, validated plan of file writes/deletes ready to apply.

    Attributes:
        files: Mapping of path to the full new content to write.
        deletes: Set of paths to remove.
        combined_diff: Human-readable unified diff across all touched files.
        touched_paths: Ordered list of all paths the patch affects.
    """

    files: dict[str, str]
    deletes: set[str]
    combined_diff: str
    touched_paths: list[str]


def _unified_diff(old: str, new: str, path: str) -> str:
    """Render a unified diff between ``old`` and ``new`` text for ``path``."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    if not old_lines and not new_lines:
        old_lines, new_lines = [""], [""]
    chunks = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    text = "\n".join(chunks)
    return text if text else "(no changes detected)"


def _normalize_patch_text(patch_text: str) -> str:
    """Normalize line endings and strip an enclosing Markdown code fence."""
    text = patch_text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def _parse_path_header(raw: str) -> str:
    """Extract a clean path from a ``---``/``+++`` header (strips ``a/``/``b/``, quotes)."""
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    if value in {"/dev/null", "dev/null", "nul"}:
        return "/dev/null"
    for prefix in ("a/", "b/"):
        if value.startswith(prefix):
            return value[2:]
    return value


def _pick_file_path(old_path: str, new_path: str) -> tuple[str, bool, bool]:
    """Choose the effective path and ``(is_new_file, is_delete)`` flags from headers."""
    if old_path == "/dev/null":
        return new_path, True, False
    if new_path == "/dev/null":
        return old_path, False, True
    return new_path or old_path, False, False


def _parse_hunk(lines: list[str], index: int) -> tuple[Hunk, int]:
    """Parse one ``@@`` hunk starting at ``index``.

    Args:
        lines: All patch lines.
        index: Index of the ``@@`` header line to parse.

    Returns:
        A tuple of the parsed :class:`Hunk` and the index of the first line after
        the hunk body.

    Raises:
        ValueError: If the line at ``index`` is not a valid hunk header.
    """
    header = lines[index]
    match = _HUNK_HEADER.match(header)
    if not match:
        raise ValueError(f"invalid hunk header: {header}")
    old_start = int(match.group(1))
    old_count = int(match.group(2) or "1")
    new_start = int(match.group(3))
    new_count = int(match.group(4) or "1")
    body: list[str] = []
    index += 1
    while index < len(lines):
        line = lines[index]
        if line.startswith("@@ ") or line.startswith("--- "):
            break
        if line == _NO_NL:
            index += 1
            continue
        if line and line[0] in {" ", "-", "+"}:
            body.append(line)
            index += 1
            continue
        if not line.strip():
            index += 1
            continue
        break
    return (
        Hunk(
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            lines=body,
        ),
        index,
    )


def parse_unified_patch(patch_text: str) -> list[FilePatch]:
    """Parse unified-diff text into a list of :class:`FilePatch` objects.

    Args:
        patch_text: The raw patch text in unified (git) diff format.

    Returns:
        One :class:`FilePatch` per file referenced in the patch.

    Raises:
        ValueError: If the patch is empty, malformed, or contains no files.
    """
    text = _normalize_patch_text(patch_text)
    if not text.strip():
        raise ValueError("empty patch")

    lines = text.splitlines()
    patches: list[FilePatch] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old_path = _parse_path_header(lines[index][4:])
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise ValueError("missing +++ line after ---")
        new_path = _parse_path_header(lines[index][4:])
        path, is_new_file, is_delete = _pick_file_path(old_path, new_path)
        index += 1
        hunks: list[Hunk] = []
        while index < len(lines) and not lines[index].startswith("--- "):
            if lines[index].startswith("@@ "):
                hunk, index = _parse_hunk(lines, index)
                hunks.append(hunk)
            else:
                index += 1
        if not hunks and not is_delete:
            raise ValueError(f"the patch for `{path}` has no hunks")
        patches.append(
            FilePatch(
                path=path,
                hunks=hunks,
                is_new_file=is_new_file,
                is_delete=is_delete,
            )
        )
    if not patches:
        raise ValueError("no files found in the patch")
    return patches


def _hunk_matches_at(lines: list[str], hunk: Hunk, src_index: int) -> bool:
    """Return whether the hunk's context/deletion lines match at ``src_index``."""
    index = src_index
    for raw_line in hunk.lines:
        if raw_line == _NO_NL:
            continue
        tag = raw_line[0]
        text = raw_line[1:]
        if tag == " " or tag == "-":
            if index >= len(lines) or lines[index] != text:
                return False
            index += 1
    return True


def _locate_hunk(lines: list[str], hunk: Hunk, *, path: str) -> int:
    """Find the source line index where ``hunk`` should be applied.

    Prefers the hunk's declared ``old_start``; otherwise picks the unique or
    nearest matching position.

    Args:
        lines: Current source lines of the file.
        hunk: The hunk to locate.
        path: File path, used only for the error message.

    Returns:
        The 0-based source index where the hunk matches.

    Raises:
        ValueError: If no position in the file matches the hunk's context.
    """
    preferred = max(0, (hunk.old_start or 1) - 1)
    matches = [index for index in range(len(lines) + 1) if _hunk_matches_at(lines, hunk, index)]
    if not matches:
        raise ValueError(
            f"patch context not found in `{path}`; "
            "re-read the file and build the hunk with context lines"
        )
    if preferred in matches:
        return preferred
    if len(matches) == 1:
        return matches[0]
    return min(matches, key=lambda index: abs(index - preferred))


def _apply_hunk_at(
    lines: list[str],
    hunk: Hunk,
    src_index: int,
    *,
    path: str,
) -> list[str]:
    """Apply ``hunk`` to ``lines`` at ``src_index``, returning the new lines.

    Args:
        lines: Current source lines of the file.
        hunk: The hunk to apply.
        src_index: 0-based index where the hunk starts (from :func:`_locate_hunk`).
        path: File path, used only for error messages.

    Returns:
        The full list of lines after applying the hunk.

    Raises:
        ValueError: If a context or deletion line does not match the source.
    """
    result = lines[:src_index]
    for raw_line in hunk.lines:
        if raw_line == _NO_NL:
            continue
        tag = raw_line[0]
        text = raw_line[1:]
        if tag == " ":
            if src_index >= len(lines) or lines[src_index] != text:
                expected = lines[src_index] if src_index < len(lines) else "<out of range>"
                raise ValueError(
                    f"context does not match in `{path}` line {src_index + 1}: "
                    f"expected `{text}`, found `{expected}`"
                )
            result.append(text)
            src_index += 1
        elif tag == "-":
            if src_index >= len(lines) or lines[src_index] != text:
                expected = lines[src_index] if src_index < len(lines) else "<out of range>"
                raise ValueError(
                    f"could not delete in `{path}` line {src_index + 1}: "
                    f"expected `{text}`, found `{expected}`"
                )
            src_index += 1
        elif tag == "+":
            result.append(text)
    result.extend(lines[src_index:])
    return result


def _apply_hunk(lines: list[str], hunk: Hunk, *, path: str) -> list[str]:
    """Locate and apply ``hunk`` to ``lines``, returning the new lines."""
    src_index = _locate_hunk(lines, hunk, path=path)
    return _apply_hunk_at(lines, hunk, src_index, path=path)


def _read_file_lines(cwd: str, path: str, *, is_new_file: bool) -> list[str]:
    """Read a file's lines, returning ``[]`` for a not-yet-existing new file.

    Args:
        cwd: The current working directory used to resolve ``path``.
        path: Workspace-relative path to read.
        is_new_file: Whether the patch is expected to create this file.

    Returns:
        The file's lines (without keepends), or ``[]`` if the file is missing
        and ``is_new_file`` is True.

    Raises:
        ValueError: If the file is missing and ``is_new_file`` is False.
    """
    resolved = resolve_path(path, cwd)
    if not resolved.is_file():
        if is_new_file:
            return []
        raise ValueError(f"file does not exist `{path}`")
    return resolved.read_text(encoding="utf-8", errors="replace").splitlines()


def plan_patch(cwd: str, patch_text: str) -> tuple[PatchPlan | None, str | None]:
    """Parse and resolve a patch into a :class:`PatchPlan` without writing.

    Validates paths, blocks sensitive files, and applies every hunk in memory to
    compute the resulting file contents and a combined diff.

    Args:
        cwd: The current working directory used to resolve paths.
        patch_text: The raw patch text in unified (git) diff format.

    Returns:
        A ``(plan, error)`` tuple: on success ``(PatchPlan, None)``; on failure
        ``(None, "Error: ...")`` (or a secret-file block message).
    """
    try:
        file_patches = parse_unified_patch(patch_text)
    except (ValueError, PathViolationError) as exc:
        return None, f"Error: {exc}"

    pending: dict[str, str] = {}
    deletes: set[str] = set()
    diff_chunks: list[str] = []
    touched: list[str] = []

    for file_patch in file_patches:
        path = file_patch.path
        if is_sensitive_path(resolve_path(path, cwd)):
            return None, secret_file_block_message()

        try:
            current_lines = _read_file_lines(
                cwd,
                path,
                is_new_file=file_patch.is_new_file,
            )
        except (ValueError, PathViolationError) as exc:
            return None, f"Error: {exc}"

        updated_lines = current_lines
        for hunk in file_patch.hunks:
            try:
                updated_lines = _apply_hunk(updated_lines, hunk, path=path)
            except ValueError as exc:
                return None, f"Error: {exc}"

        resolved = resolve_path(path, cwd)
        had_trailing_newline = resolved.is_file() and resolved.read_bytes().endswith(b"\n")
        old_text = "\n".join(current_lines)
        if had_trailing_newline:
            old_text += "\n"

        if file_patch.is_delete:
            deletes.add(path)
            new_text = ""
        else:
            new_text = "\n".join(updated_lines)
            if new_text and not new_text.endswith("\n"):
                new_text += "\n"

        pending[path] = new_text
        touched.append(path)
        diff_chunks.append(_unified_diff(old_text, new_text, path))

    combined = "\n".join(chunk for chunk in diff_chunks if chunk)
    return (
        PatchPlan(
            files=pending,
            deletes=deletes,
            combined_diff=combined,
            touched_paths=touched,
        ),
        None,
    )


def apply_patch(cwd: str, patch_text: str) -> str:
    """Apply a unified-diff patch to disk within the workspace.

    Args:
        cwd: The current working directory used to resolve paths.
        patch_text: The raw patch text in unified (git) diff format.

    Returns:
        A success message summarizing the touched files, or an ``"Error: ..."``
        message (or secret-file block message) if planning failed.
    """
    plan, error = plan_patch(cwd, patch_text)
    if error:
        return error
    assert plan is not None

    for path, content in plan.files.items():
        resolved = resolve_path(path, cwd)
        if is_sensitive_path(resolved):
            return secret_file_block_message()
        if path in plan.deletes:
            if resolved.is_file():
                resolved.unlink()
            continue
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")

    if len(plan.touched_paths) == 1:
        return f"Patch applied to {plan.touched_paths[0]}"
    joined = ", ".join(plan.touched_paths)
    return f"Patch applied to {len(plan.touched_paths)} files: {joined}"
