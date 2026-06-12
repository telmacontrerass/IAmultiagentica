"""Mensajes de seguimiento tras edit_file para evitar rondas redundantes."""

from __future__ import annotations

import re

from ci2lab.harness.tools.paths import resolve_path
from ci2lab.harness.types import ToolCall, ToolResult

_FILE_IN_PROMPT_RE = re.compile(
    r"(?P<path>[^\s`\"']+\.(?:py|md|txt|json|yaml|yml))\b",
    re.IGNORECASE,
)

EditSignature = tuple[str, str, str]

_SUCCESS_EDIT_PREFIX = "Editado "
_ALREADY_APPLIED_HINT = (
    "Este cambio ya está aplicado en el archivo. "
    "No repitas edit_file con el mismo old_string. "
    "Responde al usuario confirmando que el cambio está hecho; "
    "no llames más herramientas salvo que pida otro cambio distinto."
)
_SUCCESS_HINT = (
    "La edición se aplicó correctamente. "
    "Responde al usuario confirmando el resultado; "
    "no vuelvas a llamar edit_file ni read_file para el mismo cambio."
)


def edit_signature(call: ToolCall) -> EditSignature | None:
    if call.name != "edit_file":
        return None
    path = str(call.arguments.get("path", ""))
    if not path:
        return None
    return (
        path,
        str(call.arguments.get("old_string", "")),
        str(call.arguments.get("new_string", "")),
    )


def edit_already_applied(cwd: str, path: str, old_string: str, new_string: str) -> bool:
    """True si old_string ya no está y new_string sí (mismo edit_file repetido)."""
    if not new_string:
        return False
    try:
        resolved = resolve_path(path, cwd)
        if not resolved.is_file():
            return False
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if old_string and old_string in text:
        return False
    return new_string in text


def stale_old_string_hint(cwd: str, path: str, old_string: str) -> str | None:
    """Cuando old_string ya no está en disco, muestra el contenido actual."""
    if not old_string:
        return None
    try:
        resolved = resolve_path(path, cwd)
        if not resolved.is_file():
            return None
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if old_string in text:
        return None
    lines = text.splitlines()
    preview = "\n".join(f"  {index + 1}|{line}" for index, line in enumerate(lines[:12]))
    if len(lines) > 12:
        preview += f"\n  ... ({len(lines)} líneas en total)"
    return (
        f"`{old_string}` ya no está en `{path}`; el archivo cambió desde la última lectura. "
        f"Contenido actual:\n{preview}\n"
        "Llama a read_file y usa el texto exacto de la línea a cambiar como old_string."
    )


def _is_successful_edit(result: ToolResult) -> bool:
    return (
        not result.is_error
        and result.tool_name == "edit_file"
        and result.content.startswith(_SUCCESS_EDIT_PREFIX)
    )


def _dedupe_hints(hints: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for hint in hints:
        if hint not in seen:
            seen.add(hint)
            unique.append(hint)
    return unique


def process_edit_round(
    calls: list[ToolCall],
    results: list[ToolResult],
    *,
    cwd: str,
    user_prompt: str,
    completed_edits: set[EditSignature],
) -> str | None:
    """Registra ediciones exitosas y devuelve hints para el siguiente turno del modelo."""
    hints: list[str] = []
    had_successful_edit = False
    had_redundant_retry = False
    mentioned = _FILE_IN_PROMPT_RE.findall(user_prompt)
    mentioned_path = mentioned[0] if mentioned else None

    for call, result in zip(calls, results, strict=False):
        sig = edit_signature(call)
        if sig and _is_successful_edit(result):
            completed_edits.add(sig)
            had_successful_edit = True

        if not result.is_error:
            continue
        if result.tool_name not in {"edit_file", "write_file", "apply_patch"}:
            continue

        content = result.content
        if "no existe el archivo" in content:
            hint = (
                "La ruta del archivo era incorrecta. No inventes rutas de ejemplo "
                "como src/main.py. Llama primero a read_file con la ruta exacta "
                "que pidió el usuario (relativa a la raíz del workspace)."
            )
            if mentioned_path:
                hint += f" El usuario mencionó `{mentioned_path}`."
            hints.append(hint)
            continue

        if "old_string y new_string son iguales" in content:
            hints.append(
                "old_string y new_string deben ser distintos. "
                "Lee el archivo con read_file y cambia solo la línea pedida."
            )
            continue

        if "old_string no encontrado" in content:
            if sig and (
                sig in completed_edits
                or edit_already_applied(cwd, sig[0], sig[1], sig[2])
            ):
                hints.append(_ALREADY_APPLIED_HINT)
                had_redundant_retry = True
            else:
                stale = stale_old_string_hint(cwd, sig[0], sig[1]) if sig else None
                hints.append(
                    stale
                    or (
                        "old_string no coincide con el archivo actual. "
                        "Vuelve a llamar a read_file y copia el texto exacto de la línea a cambiar."
                    )
                )
            continue

        if "no se encontró contexto del parche" in content:
            hints.append(
                "El parche no encaja. Llama a read_file, copia las líneas reales "
                "y genera apply_patch con esas líneas en el hunk."
            )

    if had_successful_edit and not had_redundant_retry:
        hints.append(_SUCCESS_HINT)

    unique = _dedupe_hints(hints)
    return "\n".join(unique) if unique else None
