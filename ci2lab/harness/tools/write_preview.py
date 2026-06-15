"""Diff preview y validación previa para write_file y edit_file."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from ci2lab.harness.tools.paths import resolve_path
from ci2lab.harness.tools.secret_files import is_sensitive_path, secret_file_block_message

MAX_DISPLAY_LINES = 80
MAX_NEW_FILE_PREVIEW_CHARS = 2000


@dataclass
class WritePreview:
    path: str
    is_new_file: bool
    diff: str
    validation_error: str | None = None
    new_content: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.validation_error is None

    def format_for_display(self) -> str:
        lines = [f"Archivo: {self.path}"]
        if self.validation_error:
            lines.append(f"Error de validación: {self.validation_error}")
            return "\n".join(lines)
        if self.is_new_file:
            lines.append("Acción: crear archivo nuevo")
            preview = self.new_content or ""
            if len(preview) > MAX_NEW_FILE_PREVIEW_CHARS:
                preview = (
                    preview[:MAX_NEW_FILE_PREVIEW_CHARS]
                    + f"\n… ({len(self.new_content or '')} caracteres totales)"
                )
            lines.append("--- contenido propuesto ---")
            lines.append(preview)
        else:
            lines.append("Acción: modificar archivo existente")
            lines.append("--- diff unificado ---")
            lines.extend(_truncate_diff_lines(self.diff))
        return "\n".join(lines)


def _truncate_diff_lines(diff: str) -> list[str]:
    rows = diff.splitlines()
    if len(rows) <= MAX_DISPLAY_LINES:
        return rows
    head = rows[:MAX_DISPLAY_LINES]
    head.append(f"… ({len(rows) - MAX_DISPLAY_LINES} líneas más en el diff)")
    return head


def _unified_diff(old: str, new: str, path: str) -> str:
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
    return text if text else "(sin cambios detectados)"


def compute_edit_result(
    cwd: str,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> tuple[str | None, str | None]:
    """Devuelve (nuevo_contenido, mensaje_error)."""
    if old_string == new_string:
        return None, "Error: old_string y new_string son iguales; no hay cambio que aplicar"
    resolved = resolve_path(path, cwd)
    if not resolved.is_file():
        from ci2lab.harness.tools.file_hints import format_missing_file_error

        return None, format_missing_file_error(cwd, resolved)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        return None, "Error: old_string no encontrado en el archivo"
    if not replace_all and count > 1:
        return (
            None,
            f"Error: old_string aparece {count} veces; usa replace_all o hazlo único",
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
            validation_error="Error: write_docx solo admite rutas .docx",
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
            current = "(no se pudo extraer el .docx actual para diff)"
        return WritePreview(
            path=rel,
            is_new_file=False,
            diff=_unified_diff(current, content, rel),
            new_content="[Se convertirá markdown -> .docx con pandoc]\n" + content,
        )
    return WritePreview(
        path=rel,
        is_new_file=True,
        diff="",
        new_content="[Nuevo .docx desde markdown vía pandoc]\n" + content,
    )


def preview_write_file(
    cwd: str,
    path: str,
    content: str,
    *,
    enforce_hard_policy: bool = True,
) -> WritePreview:
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
    new_text, error = compute_edit_result(
        cwd, path, old_string, new_string, replace_all
    )
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
    if not plan.combined_diff or plan.combined_diff == "(sin cambios detectados)":
        return WritePreview(
            path="apply_patch",
            is_new_file=False,
            diff="",
            validation_error="Error: el parche no introduce cambios",
        )
    if len(plan.touched_paths) == 1:
        path_label = plan.touched_paths[0]
    else:
        path_label = f"{len(plan.touched_paths)} archivos: {', '.join(plan.touched_paths)}"
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
    """Shared preview builder for docx_to_pdf and pdf_to_docx."""
    from ci2lab.harness.tools.paths import PathViolationError

    try:
        source_path = resolve_path(source, cwd)
        output_path = resolve_path(output, cwd)
    except PathViolationError as exc:
        return WritePreview(
            path=output or "(sin output)",
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
                f"Error: {tool_name} requiere un archivo fuente {source_ext}, "
                f"no '{source_path.suffix}'"
            ),
        )
    if output_path.suffix.lower() != output_ext:
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error=(
                f"Error: {tool_name} requiere una ruta de salida {output_ext}, "
                f"no '{output_path.suffix}'"
            ),
        )
    if not source_path.is_file():
        return WritePreview(
            path=output,
            is_new_file=True,
            diff="",
            validation_error=f"Error: archivo fuente no encontrado: {source}",
        )

    rel_out = _display_path(output_path, cwd)
    overwrite_note = "existente — se sobreescribirá" if output_path.is_file() else "archivo nuevo"
    summary = (
        f"Fuente : {source}\n"
        f"Salida : {output} ({overwrite_note})\n"
        f"Método : {source_ext} → {output_ext}"
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
    try:
        return str(resolved.relative_to(Path(cwd).resolve()))
    except ValueError:
        return str(resolved)
