"""Diff preview and pre-validation for write_file and edit_file."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from ci2lab.harness.tools.paths import resolve_path
from ci2lab.harness.tools.secret_files import is_sensitive_path, secret_file_block_message

#: Maximum number of unified-diff lines to show before truncating the preview.
MAX_DISPLAY_LINES: int = 80
#: Maximum number of characters of new-file content to show in a preview.
MAX_NEW_FILE_PREVIEW_CHARS: int = 2000


@dataclass
class WritePreview:
    """Result of pre-validating a write/edit operation before it is applied.

    Attributes:
        path: Display path (workspace-relative where possible) of the target.
        is_new_file: Whether the operation would create a new file.
        diff: Unified diff of the change (empty for new-file/conversion previews).
        validation_error: Error message when the operation is invalid, else
            ``None``.
        new_content: Proposed file content or a human-readable summary, when
            available.
    """

    path: str
    is_new_file: bool
    diff: str
    validation_error: str | None = None
    new_content: str | None = None

    @property
    def is_valid(self) -> bool:
        """Whether the previewed operation passed validation."""
        return self.validation_error is None

    def format_for_display(self) -> str:
        """Render a human-readable summary of the preview for confirmation UIs.

        Returns:
            A multi-line string describing the validation error, the proposed
            new-file content, or the (possibly truncated) unified diff.
        """
        lines = [f"File: {self.path}"]
        if self.validation_error:
            lines.append(f"Validation error: {self.validation_error}")
            return "\n".join(lines)
        if self.is_new_file:
            lines.append("Action: create new file")
            preview = self.new_content or ""
            if len(preview) > MAX_NEW_FILE_PREVIEW_CHARS:
                preview = (
                    preview[:MAX_NEW_FILE_PREVIEW_CHARS]
                    + f"\n… ({len(self.new_content or '')} characters total)"
                )
            lines.append("--- proposed content ---")
            lines.append(preview)
        else:
            lines.append("Action: modify existing file")
            lines.append("--- unified diff ---")
            lines.extend(_truncate_diff_lines(self.diff))
        return "\n".join(lines)


def _truncate_diff_lines(diff: str) -> list[str]:
    """Split a diff into lines, truncating to ``MAX_DISPLAY_LINES`` with a note."""
    rows = diff.splitlines()
    if len(rows) <= MAX_DISPLAY_LINES:
        return rows
    head = rows[:MAX_DISPLAY_LINES]
    head.append(f"… ({len(rows) - MAX_DISPLAY_LINES} more lines in the diff)")
    return head


def _unified_diff(old: str, new: str, path: str) -> str:
    """Build a unified diff string between ``old`` and ``new`` for ``path``."""
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


def compute_edit_result(
    cwd: str,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> tuple[str | None, str | None]:
    """Compute the file content resulting from an ``edit_file`` operation.

    Args:
        cwd: Workspace root used to resolve ``path``.
        path: Target file path (relative to ``cwd`` or absolute).
        old_string: Substring to be replaced; must exist in the file.
        new_string: Replacement text; must differ from ``old_string``.
        replace_all: Replace every occurrence instead of requiring a unique one.

    Returns:
        A tuple ``(new_content, error_message)`` where exactly one element is
        non-``None``: the new file content on success, or an error message
        string describing why the edit cannot be applied.
    """
    if old_string == new_string:
        return None, "Error: old_string and new_string are identical; nothing to change"
    resolved = resolve_path(path, cwd)
    if not resolved.is_file():
        from ci2lab.harness.tools.file_hints import format_missing_file_error

        return None, format_missing_file_error(cwd, resolved)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        return None, "Error: old_string not found in the file"
    if not replace_all and count > 1:
        return (
            None,
            f"Error: old_string appears {count} times; use replace_all or make it unique",
        )
    replacements = count if replace_all else 1
    new_text = text.replace(old_string, new_string, replacements)
    return new_text, None


def preview_write_docx(cwd: str, path: str, content: str) -> WritePreview:
    """Preview creating or replacing a DOCX from markdown source."""
    resolved = resolve_path(path, cwd)
    rel = _display_path(resolved, cwd)
    if resolved.suffix.lower() != ".docx":
        return WritePreview(
            path=rel,
            is_new_file=not resolved.is_file(),
            diff="",
            validation_error="Error: write_docx only accepts .docx paths",
        )
    if is_sensitive_path(resolved, workspace=cwd):
        return WritePreview(
            path=rel,
            is_new_file=not resolved.is_file(),
            diff="",
            validation_error=secret_file_block_message(),
        )
    if resolved.is_file():
        from ci2lab.harness.tools.docx import extract_docx_markdown

        current = extract_docx_markdown(resolved)
        if current.startswith("Error:"):
            current = "(could not extract the current .docx for diff)"
        return WritePreview(
            path=rel,
            is_new_file=False,
            diff=_unified_diff(current, content, rel),
            new_content="[Will convert markdown -> .docx with pandoc]\n" + content,
        )
    return WritePreview(
        path=rel,
        is_new_file=True,
        diff="",
        new_content="[New .docx from markdown via pandoc]\n" + content,
    )


def preview_write_file(
    cwd: str,
    path: str,
    content: str,
    *,
    enforce_hard_policy: bool = True,
) -> WritePreview:
    """Preview creating or overwriting a file with ``content``.

    Args:
        cwd: Workspace root used to resolve ``path``.
        path: Target file path (relative to ``cwd`` or absolute).
        content: Full proposed file content.
        enforce_hard_policy: When ``True``, resolve through the hard path policy
            and block sensitive paths; when ``False``, resolve leniently.

    Returns:
        A :class:`WritePreview` with a diff against existing content or a
        new-file preview, or a validation error for blocked sensitive paths.
    """
    if enforce_hard_policy:
        resolved = resolve_path(path, cwd)
    else:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        resolved = candidate.resolve()
    rel = _display_path(resolved, cwd)
    if enforce_hard_policy and is_sensitive_path(resolved, workspace=cwd):
        return WritePreview(
            path=rel,
            is_new_file=not resolved.is_file(),
            diff="",
            validation_error=secret_file_block_message(),
        )
    if resolved.is_file():
        current = resolved.read_text(encoding="utf-8", errors="replace")
        return WritePreview(
            path=rel,
            is_new_file=False,
            diff=_unified_diff(current, content, rel),
            new_content=content,
        )
    return WritePreview(
        path=rel,
        is_new_file=True,
        diff="",
        new_content=content,
    )


def preview_edit_file(
    cwd: str,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    *,
    enforce_hard_policy: bool = True,
) -> WritePreview:
    """Preview an ``edit_file`` substitution against an existing file.

    Args:
        cwd: Workspace root used to resolve ``path``.
        path: Target file path (relative to ``cwd`` or absolute).
        old_string: Substring to be replaced.
        new_string: Replacement text.
        replace_all: Replace every occurrence instead of requiring a unique one.
        enforce_hard_policy: When ``True``, resolve through the hard path policy
            and block sensitive paths; when ``False``, resolve leniently.

    Returns:
        A :class:`WritePreview` with the unified diff of the proposed edit, or a
        validation error when the edit cannot be applied or the path is blocked.
    """
    if enforce_hard_policy:
        resolved = resolve_path(path, cwd)
    else:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        resolved = candidate.resolve()
    rel = _display_path(resolved, cwd)
    if enforce_hard_policy and is_sensitive_path(resolved, workspace=cwd):
        return WritePreview(
            path=rel,
            is_new_file=False,
            diff="",
            validation_error=secret_file_block_message(),
        )
    new_text, error = compute_edit_result(cwd, path, old_string, new_string, replace_all)
    if error:
        return WritePreview(
            path=rel,
            is_new_file=False,
            diff="",
            validation_error=error,
        )
    current = resolved.read_text(encoding="utf-8", errors="replace")
    return WritePreview(
        path=rel,
        is_new_file=False,
        diff=_unified_diff(current, new_text or "", rel),
        new_content=new_text,
    )


def preview_apply_patch(cwd: str, patch_text: str) -> WritePreview:
    """Preview the combined effect of an ``apply_patch`` unified diff.

    Args:
        cwd: Workspace root against which the patch is planned.
        patch_text: The unified-diff patch text to apply.

    Returns:
        A :class:`WritePreview` carrying the combined diff and a label of the
        touched path(s), or a validation error when the patch is invalid or a
        no-op.
    """
    from ci2lab.harness.tools.patch import plan_patch

    plan, error = plan_patch(cwd, patch_text)
    if error:
        return WritePreview(
            path="apply_patch",
            is_new_file=False,
            diff="",
            validation_error=error,
        )
    assert plan is not None
    if not plan.combined_diff or plan.combined_diff == "(no changes detected)":
        return WritePreview(
            path="apply_patch",
            is_new_file=False,
            diff="",
            validation_error="Error: the patch introduces no changes",
        )
    if len(plan.touched_paths) == 1:
        path_label = plan.touched_paths[0]
    else:
        path_label = f"{len(plan.touched_paths)} files: {', '.join(plan.touched_paths)}"
    return WritePreview(
        path=path_label,
        is_new_file=False,
        diff=plan.combined_diff,
    )


def _conversion_preview(
    cwd: str,
    source: str,
    output: str,
    source_ext: str,
    output_ext: str,
    tool_name: str,
) -> WritePreview:
    """Shared preview builder for docx_to_pdf and pdf_to_docx.

    Args:
        cwd: Workspace root used to resolve ``source`` and ``output``.
        source: Source document path.
        output: Destination document path.
        source_ext: Required lowercase suffix for the source (e.g. ``".docx"``).
        output_ext: Required lowercase suffix for the output (e.g. ``".pdf"``).
        tool_name: Name of the calling tool, used in error messages.

    Returns:
        A :class:`WritePreview` summarizing the conversion, or a validation
        error for bad extensions, missing sources or path violations.
    """
    from ci2lab.harness.tools.paths import PathViolationError

    try:
        source_path = resolve_path(source, cwd)
        output_path = resolve_path(output, cwd)
    except PathViolationError as exc:
        return WritePreview(
            path=output or "(no output)",
            is_new_file=True,
            diff="",
            validation_error=str(exc),
        )

    if source_path.suffix.lower() != source_ext:
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error=(
                f"Error: {tool_name} requires a {source_ext} source file, no '{source_path.suffix}'"
            ),
        )
    if output_path.suffix.lower() != output_ext:
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error=(
                f"Error: {tool_name} requires a {output_ext} output path, no '{output_path.suffix}'"
            ),
        )
    if not source_path.is_file():
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error=f"Error: source file not found: {source}",
        )

    rel_out = _display_path(output_path, cwd)
    overwrite_note = "existing — will be overwritten" if output_path.is_file() else "new file"
    summary = (
        f"Source : {source}\n"
        f"Output : {output} ({overwrite_note})\n"
        f"Method : {source_ext} → {output_ext}"
    )
    return WritePreview(
        path=rel_out,
        is_new_file=not output_path.is_file(),
        diff="",
        new_content=summary,
    )


def preview_docx_to_pdf(cwd: str, source: str, output: str) -> WritePreview:
    """Preview for docx_to_pdf conversion."""
    return _conversion_preview(cwd, source, output, ".docx", ".pdf", "docx_to_pdf")


def preview_pdf_to_docx(cwd: str, source: str, output: str) -> WritePreview:
    """Preview for pdf_to_docx conversion."""
    return _conversion_preview(cwd, source, output, ".pdf", ".docx", "pdf_to_docx")


def _display_path(resolved: Path, cwd: str) -> str:
    """Return ``resolved`` relative to ``cwd`` when possible, else its absolute form."""
    try:
        return str(resolved.relative_to(Path(cwd).resolve()))
    except ValueError:
        return str(resolved)
