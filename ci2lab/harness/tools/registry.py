"""Catálogo de herramientas, schemas OpenAI y despacho."""

from __future__ import annotations

import json
from typing import Any, Callable

from ci2lab.harness.tools import bash as bash_tool
from ci2lab.harness.tools import filesystem as fs
from ci2lab.harness.tools.filesystem import permission_summary
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult

TOOL_NAMES = frozenset({
    "bash",
    "read_file",
    "ls",
    "grep",
    "glob",
    "write_file",
    "edit_file",
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
            "description": "Lee un archivo del proyecto. Devuelve líneas numeradas.",
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
}


def parse_arguments(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw or not str(raw).strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"command": str(raw)} if raw else {}


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

    args = call.arguments
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
    return ToolResult(
        tool_name=name,
        content=output,
        is_error=output.startswith("Error:"),
        call_id=call.call_id,
    )
