"""Catálogo de herramientas, schemas OpenAI y despacho."""

from __future__ import annotations

import json
from typing import Any, Callable

from ci2lab.harness.tools import bash as bash_tool
from ci2lab.harness.tools import filesystem as fs
from ci2lab.harness.tools import inspection as inspection_tool
from ci2lab.harness.tools.bash import _format_bash_block_message
from ci2lab.harness.tools.arg_normalize import normalize_args_for_tool
from ci2lab.security.audit import (
    AuditPersistContext,
    get_audit_persist_context,
    log_decision,
    set_audit_persist_context,
)
from ci2lab.security.engine import ToolGateResult, enforce_ci2lab_hard_policy
from ci2lab.security.permissions import evaluate_tool_gate
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
        cfg.cwd,
        a["command"],
        cfg.bash_timeout_seconds,
        security_profile=cfg.security_profile,
        security_engine=cfg.security_engine,
    ),
    "read_file": lambda cfg, a: fs.read_file(
        cfg.cwd,
        a["path"],
        a.get("offset", 1),
        a.get("limit"),
        security_engine=cfg.security_engine,
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


def _ensure_audit_persist_context(config: AgentConfig) -> None:
    if get_audit_persist_context() is not None:
        return
    set_audit_persist_context(
        AuditPersistContext(
            workspace=config.cwd,
            runs_dir=config.runs_dir,
            security_engine=config.security_engine,
        )
    )


def _audit_security_decision(
    *,
    tool: str,
    detail: str,
    decision: str,
    gate: ToolGateResult | None = None,
    reason: str | None = None,
    confirmed: bool | None = None,
    outcome: str | None = None,
    confirm_extra: dict[str, Any] | None = None,
) -> None:
    kwargs: dict[str, Any] = {
        "tool": tool,
        "detail": detail,
        "decision": decision,
        "reason": reason or (gate.reason if gate else ""),
        "confirmed": confirmed,
        "outcome": outcome,
    }
    merged_extra: dict[str, Any] = dict(confirm_extra or {})
    if gate is not None:
        kwargs.update(
            {
                "security_engine": gate.engine,
                "matched_rule": gate.matched_rule,
                "external_directory": gate.external_directory,
                "hard_guards_enabled": gate.hard_guards_enabled,
                "permission_layer_enabled": gate.permission_layer_enabled,
                "experimental": gate.experimental,
                "session_approval_used": gate.session_approval_used,
                "session_approval_scope": gate.session_approval_scope,
            }
        )
        merged_extra.setdefault("engine", gate.engine)
    if merged_extra:
        kwargs["extra"] = merged_extra
    log_decision(**kwargs)


def _resolve_tool_confirm(
    name: str,
    args: dict[str, Any],
    detail: str,
    gate: ToolGateResult,
    config: AgentConfig,
) -> tuple[bool, str | None, str, dict[str, Any]]:
    """Confirma un ask post-gate. Devuelve allowed, deny_msg, reason, audit_extra."""
    from ci2lab.harness.permissions import check_permission
    from ci2lab.security.approval_prompt import (
        confirm_opencode_ask,
        uses_modern_permission_prompt,
    )

    if uses_modern_permission_prompt(config.security_engine):
        result = confirm_opencode_ask(
            config=config,
            tool_name=name,
            args=args,
            gate=gate,
            detail=detail,
        )
        extra = {
            "approval_choice": result.choice.value if result.choice else None,
            "session_scope_granted": result.session_scope_granted,
        }
        if result.proceed:
            return True, None, result.reason, extra
        return False, result.message, result.reason, extra

    allowed, deny_msg = check_permission(
        name,
        detail,
        auto_confirm=config.auto_confirm,
        confirm_callback=config.confirm_callback,
    )
    reason = "confirmed" if config.auto_confirm else "user_confirmed"
    if allowed:
        return True, None, reason, {}
    return False, deny_msg, "user_denied", {}


def _execute_write_tool(
    name: str,
    args: dict[str, Any],
    config: AgentConfig,
    call_id: str | None,
    *,
    gate: ToolGateResult | None = None,
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

    enforce_hard = enforce_ci2lab_hard_policy(config.security_engine)
    try:
        if name == "write_file":
            preview = preview_write_file(
                config.cwd,
                args["path"],
                args["content"],
                enforce_hard_policy=enforce_hard,
            )
        else:
            preview = preview_edit_file(
                config.cwd,
                args["path"],
                args["old_string"],
                args["new_string"],
                args.get("replace_all", False),
                enforce_hard_policy=enforce_hard,
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

    needs_confirm = gate.needs_confirm if gate is not None else True
    if needs_confirm:
        from ci2lab.security.approval_prompt import uses_modern_permission_prompt

        detail = preview.path
        if uses_modern_permission_prompt(config.security_engine) and gate is not None:
            if config.require_diff_preview:
                from rich.panel import Panel

                from ci2lab.harness.write_permissions import _console as write_console

                write_console.print(
                    Panel(
                        preview.format_for_display(),
                        title=f"Preview: {name}",
                        border_style="yellow",
                    )
                )
            _audit_security_decision(
                tool=name,
                detail=detail,
                decision="ask",
                gate=gate,
                outcome="pending",
            )
            allowed, deny_msg, reason, confirm_extra = _resolve_tool_confirm(
                name,
                args,
                detail,
                gate,
                config,
            )
            if not allowed:
                _audit_security_decision(
                    tool=name,
                    detail=detail,
                    decision="deny",
                    gate=gate,
                    reason=reason,
                    confirmed=False,
                    outcome="denied",
                    confirm_extra=confirm_extra,
                )
                return ToolResult(
                    tool_name=name,
                    content=deny_msg or "Denegado",
                    is_error=True,
                    call_id=call_id,
                    outcome="denied",
                )
            _audit_security_decision(
                tool=name,
                detail=detail,
                decision="allow",
                gate=gate,
                reason=reason,
                confirmed=True,
                outcome="executed",
                confirm_extra=confirm_extra,
            )
        else:
            from ci2lab.harness.write_permissions import check_write_permission

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
    _ensure_audit_persist_context(config)

    name = call.name
    if name not in TOOL_NAMES:
        return ToolResult(
            tool_name=name,
            content=f"Error: herramienta desconocida `{name}`",
            is_error=True,
            call_id=call.call_id,
        )

    args = normalize_tool_arguments(call.arguments, tool_name=name)

    detail = permission_summary(name, args) or str(args)[:120]
    gate = evaluate_tool_gate(name, args, config)

    if gate.blocked:
        _audit_security_decision(
            tool=name,
            detail=detail,
            decision="deny",
            gate=gate,
            outcome=gate.outcome or "blocked",
        )
        return ToolResult(
            tool_name=name,
            content=gate.message or "Error: bloqueado por politica de seguridad",
            is_error=True,
            call_id=call.call_id,
            outcome=gate.outcome,
        )

    if name in WRITE_TOOLS:
        return _execute_write_tool(name, args, config, call.call_id, gate=gate)

    if gate.needs_confirm:
        _audit_security_decision(
            tool=name,
            detail=detail,
            decision="ask",
            gate=gate,
            outcome="pending",
        )
        allowed, deny_msg, reason, confirm_extra = _resolve_tool_confirm(
            name,
            args,
            detail,
            gate,
            config,
        )
        if not allowed:
            _audit_security_decision(
                tool=name,
                detail=detail,
                decision="deny",
                gate=gate,
                reason=reason,
                confirmed=False,
                outcome="denied",
                confirm_extra=confirm_extra or None,
            )
            return ToolResult(
                tool_name=name,
                content=deny_msg or "Denegado",
                is_error=True,
                call_id=call.call_id,
                outcome="denied",
            )
        _audit_security_decision(
            tool=name,
            detail=detail,
            decision="allow",
            gate=gate,
            reason=reason,
            confirmed=True,
            outcome="executed",
            confirm_extra=confirm_extra or None,
        )
    else:
        _audit_security_decision(
            tool=name,
            detail=detail,
            decision="allow",
            gate=gate,
            outcome="executed",
        )

    try:
        output = _DISPATCH[name](config, args)
    except PathViolationError as exc:
        _audit_security_decision(
            tool=name,
            detail=detail,
            decision="deny",
            gate=gate,
            reason="outside_workspace",
            outcome="blocked_by_workspace",
        )
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
    if is_error:
        _audit_security_decision(
            tool=name,
            detail=detail,
            decision="deny",
            gate=gate,
            reason=outcome_for_tool_output(output) or "tool_error",
            outcome="error",
        )
    return ToolResult(
        tool_name=name,
        content=output,
        is_error=is_error,
        call_id=call.call_id,
        outcome=outcome_for_tool_output(output) if is_error else None,
    )
