"""Catálogo de herramientas, schemas OpenAI y despacho."""

from __future__ import annotations

import json
from typing import Any, Callable

from ci2lab.harness.tools import bash as bash_tool
from ci2lab.harness.tools import filesystem as fs
from ci2lab.harness.tools import inspection as inspection_tool
from ci2lab.harness.tools.bash import _format_bash_block_message
from ci2lab.harness.tools.arg_normalize import normalize_args_for_tool
from ci2lab.harness.tools.bash_safety import check_bash_blocked
from ci2lab.harness.tools.filesystem import permission_summary
from ci2lab.harness.policy import outcome_for_tool_output
from ci2lab.harness.tools.paths import PathViolationError
from ci2lab.harness.tools.write_preview import preview_edit_file, preview_write_file
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult
from ci2lab.harness.write_permissions import WRITE_TOOLS, check_write_permission

TOOL_NAMES = frozenset({
    "bash",
    "read_file",
    "ls",
    "grep",
    "glob",
    "write_file",
    "edit_file",
    "file_info",
    "tree",
    "inspect_file",
})

# Schemas compatibles con OpenAI function calling (extraídos/adaptados de Odysseus).
FUNCTION_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Ejecuta un comando en la shell del sistema. Usar para compilar, tests, git, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Comando a ejecutar"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lee un archivo del proyecto, incluidos PDFs con texto extraible. Devuelve líneas numeradas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "description": "Línea inicial (1-based)"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "Lista el contenido de un directorio del proyecto.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Busca un patrón regex en archivos del proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "glob": {"type": "string"},
                    "ignore_case": {"type": "boolean"},
                    "max_results": {"type": "integer"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Encuentra archivos por patrón glob (ej. **/*.py).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Crea o sobrescribe un archivo en el proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edita un archivo por reemplazo exacto de texto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_info",
            "description": "Metadatos de archivo o directorio sin leer contenido sensible.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tree",
            "description": "Arbol de directorios acotado por profundidad y numero de entradas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "depth": {"type": "integer"},
                    "max_entries": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_file",
            "description": "Lee un rango acotado de lineas de un archivo de texto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
]

_DISPATCH: dict[str, Callable[..., str]] = {
    "bash": lambda cfg, a: bash_tool.run_bash(
        cfg.cwd, a["command"], cfg.bash_timeout_seconds
    ),
    "read_file": lambda cfg, a: fs.read_file(
        cfg.cwd, a["path"], a.get("offset", 1), a.get("limit")
    ),
    "ls": lambda cfg, a: fs.ls(cfg.cwd, a.get("path", ".")),
    "grep": lambda cfg, a: fs.grep_search(
        cfg.cwd,
        a["pattern"],
        a.get("path", "."),
        a.get("glob"),
        a.get("ignore_case", False),
        a.get("max_results", 50),
    ),
    "glob": lambda cfg, a: fs.glob_search(
        cfg.cwd, a["pattern"], a.get("path", ".")
    ),
    "write_file": lambda cfg, a: fs.write_file(cfg.cwd, a["path"], a["content"]),
    "edit_file": lambda cfg, a: fs.edit_file(
        cfg.cwd,
        a["path"],
        a["old_string"],
        a["new_string"],
        a.get("replace_all", False),
    ),
    "file_info": lambda cfg, a: inspection_tool.file_info(cfg.cwd, a["path"]),
    "tree": lambda cfg, a: inspection_tool.tree(
        cfg.cwd,
        a.get("path", "."),
        a.get("depth", 2),
        a.get("max_entries", 200),
    ),
    "inspect_file": lambda cfg, a: inspection_tool.inspect_file(
        cfg.cwd,
        a["path"],
        a.get("start", 1),
        a.get("end"),
        a.get("max_lines", 120),
    ),
}


def normalize_tool_arguments(
    args: dict[str, Any],
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """
    Limpia argumentos de tool calls del modelo.

    Ollama y otros backends envían a menudo null explícito en campos opcionales
    (p. ej. offset/limit en read_file), lo que rompe .get(key, default).
    """
    cleaned = {k: v for k, v in args.items() if v is not None}
    if tool_name:
        return normalize_args_for_tool(tool_name, cleaned)
    return cleaned


def parse_arguments(
    raw: str | dict[str, Any],
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    if isinstance(raw, dict):
        return normalize_tool_arguments(raw, tool_name=tool_name)
    if not raw or not str(raw).strip():
        return {}
    try:
        return normalize_tool_arguments(json.loads(raw), tool_name=tool_name)
    except json.JSONDecodeError:
        return {"command": str(raw)} if raw else {}


def _execute_write_tool(
    name: str,
    args: dict[str, Any],
    config: AgentConfig,
    call_id: str | None,
) -> ToolResult:
    if not config.write_tools_enabled:
        return ToolResult(
            tool_name=name,
            content=(
                f"Error: `{name}` deshabilitado por configuración "
                "(write_tools_enabled=false)."
            ),
            is_error=True,
            call_id=call_id,
            outcome="blocked_by_config",
        )

    try:
        if name == "write_file":
            preview = preview_write_file(
                config.cwd, args["path"], args["content"]
            )
        else:
            preview = preview_edit_file(
                config.cwd,
                args["path"],
                args["old_string"],
                args["new_string"],
                args.get("replace_all", False),
            )
    except PathViolationError as exc:
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call_id,
            outcome="blocked_by_workspace",
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call_id,
            outcome="failed",
        )

    if not preview.is_valid:
        err_msg = preview.validation_error or "Error de validación"
        return ToolResult(
            tool_name=name,
            content=err_msg,
            is_error=True,
            call_id=call_id,
            outcome=outcome_for_tool_output(err_msg) or "failed",
        )

    allowed, deny_msg = check_write_permission(name, preview, config)
    if not allowed:
        return ToolResult(
            tool_name=name,
            content=deny_msg or "Denegado",
            is_error=True,
            call_id=call_id,
            outcome="denied",
        )

    try:
        output = _DISPATCH[name](config, args)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call_id,
            outcome="failed",
        )

    is_error = output.startswith("Error:")
    return ToolResult(
        tool_name=name,
        content=output,
        is_error=is_error,
        call_id=call_id,
        outcome="failed" if is_error else "approved",
    )


def execute_tool(call: ToolCall, config: AgentConfig) -> ToolResult:
    from ci2lab.harness.permissions import check_permission

    name = call.name
    if name not in TOOL_NAMES:
        return ToolResult(
            tool_name=name,
            content=f"Error: herramienta desconocida `{name}`",
            is_error=True,
            call_id=call.call_id,
        )

    args = normalize_tool_arguments(call.arguments, tool_name=name)

    if name in WRITE_TOOLS:
        return _execute_write_tool(name, args, config, call.call_id)

    if name == "bash":
        blocked = check_bash_blocked(
            str(args.get("command", "")),
            cwd=config.cwd,
        )
        if blocked:
            return ToolResult(
                tool_name=name,
                content=_format_bash_block_message(blocked),
                is_error=True,
                call_id=call.call_id,
                outcome="blocked_by_workspace",
            )

    allowed, deny_msg = check_permission(
        name,
        permission_summary(name, args),
        auto_confirm=config.auto_confirm,
        confirm_callback=config.confirm_callback,
    )
    if not allowed:
        return ToolResult(
            tool_name=name,
            content=deny_msg or "Denegado",
            is_error=True,
            call_id=call.call_id,
        )

    try:
        output = _DISPATCH[name](config, args)
    except PathViolationError as exc:
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call.call_id,
            outcome="blocked_by_workspace",
        )
    except Exception as exc:  # noqa: BLE001 — devolver error al modelo
        return ToolResult(
            tool_name=name,
            content=f"Error: {exc}",
            is_error=True,
            call_id=call.call_id,
        )

    if len(output) > config.max_tool_output_chars:
        output = (
            output[: config.max_tool_output_chars]
            + f"\n... (truncado, {len(output)} caracteres totales)"
        )
    is_error = output.startswith("Error:")
    return ToolResult(
        tool_name=name,
        content=output,
        is_error=is_error,
        call_id=call.call_id,
        outcome=outcome_for_tool_output(output) if is_error else None,
    )
