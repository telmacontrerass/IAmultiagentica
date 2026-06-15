"""Simple write/edit filesystem tools."""

from __future__ import annotations

from ci2lab.harness.tools.filesystem_parts.access import resolve_or_error
from ci2lab.harness.tools.secret_files import is_sensitive_path, secret_file_block_message


def write_file(cwd: str, path: str, content: str) -> str:
    resolved, err = resolve_or_error(path, cwd)
    if err:
        return err
    assert resolved is not None
    if is_sensitive_path(resolved, workspace=cwd):
        return secret_file_block_message()
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
    from ci2lab.harness.tools.write_preview import compute_edit_result

    resolved, err = resolve_or_error(path, cwd)
    if err:
        return err
    assert resolved is not None
    if is_sensitive_path(resolved, workspace=cwd):
        return secret_file_block_message()
    if resolved.is_file():
        original_count = resolved.read_text(encoding="utf-8", errors="replace").count(
            old_string
        )
    else:
        original_count = 0

    new_text, error = compute_edit_result(
        cwd, path, old_string, new_string, replace_all
    )
    if error:
        return error
    resolved.write_text(new_text or "", encoding="utf-8")
    replaced = original_count if replace_all else 1
    return f"Editado {resolved}: {replaced} reemplazo(s)"

