"""Catálogo de herramientas, schemas OpenAI y despacho."""

from __future__ import annotations

import json
from typing import Any, Callable

from ci2lab.harness.tools import ask_user as ask_user_tool
from ci2lab.harness.tools import bash as bash_tool
from ci2lab.harness.tools import filesystem as fs
from ci2lab.harness.tools import git_tools
from ci2lab.harness.tools import inspection as inspection_tool
from ci2lab.harness.tools import notebook as notebook_tool
from ci2lab.harness.tools import todo as todo_tool
from ci2lab.harness.tools import skill_tool
from ci2lab.harness.tools import web as web_tool
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
    "read_document",
    "read_file",
    "ls",
    "grep",
    "glob",
    "write_file",
    "edit_file",
    "file_info",
    "tree",
    "inspect_file",
    "todo_write",
    "ask_user",
    "web_fetch",
    "notebook_edit",
    "git_status",
    "git_diff",
    "skill",
    "mcp_call",
})


def is_known_tool(name: str) -> bool:
    if name in TOOL_NAMES:
        return True
    return name.startswith("mcp__")

# Schemas compatibles con OpenAI function calling (extraídos/adaptados de Odysseus).
FUNCTION_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command (build, tests, installs, running scripts). Asks for confirmation. Prefer read-only tools for exploring; use bash only when no read-only tool fits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a whole text/code file and return numbered lines. For PDF, Word, PowerPoint, Excel, CSV, Markdown or teaching documents, prefer read_document. For a known line range of a large file, use inspect_file instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "description": "First line to read (1-based)"},
                    "limit": {"type": "integer", "description": "Max number of lines to read"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": (
                "Lee documentos docentes o de oficina y detecta el formato: "
                "PDF con texto, DOCX, PPTX, XLSX, CSV, Markdown y texto plano. "
                "Devuelve metadatos y texto extraido."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "List the entries of one directory. For a recursive view use tree.",
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
            "description": "Search file contents by regex across the workspace. Use to find where text or symbols appear.",
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
            "description": "Find files by name pattern (e.g. **/*.py). Use to locate files by name, not by content.",
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
            "description": "Create or overwrite a file with plain text. Put the full file text in `content`. Not for .docx or other binary formats.",
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
            "description": "Edit an existing file by exact text replacement. `old_string` must match the current text exactly.",
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
            "description": "Get metadata for a file or directory (size, type) without reading its content.",
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
            "description": "Show a bounded directory tree (control depth and max_entries). Use to understand project layout cheaply.",
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
            "description": "Read a bounded line range of a text file. Cheaper than read_file for large files when you know the range.",
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
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": (
                "Replace the workspace task list (.ci2lab/todos.json) for multi-step work. "
                "Each item needs content and status (pending, in_progress, completed, cancelled)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {"type": "string"},
                            },
                            "required": ["content"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Ask the user a question when you need a decision. "
                "Blocks until the user answers in the terminal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional numbered choices",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch a public http(s) URL and return text (HTML is stripped). "
                "Use for docs or reference pages, not for secrets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Max characters to return (default 80000)",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notebook_edit",
            "description": "Edit one cell in a Jupyter .ipynb notebook.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "cell_index": {
                        "type": "integer",
                        "description": "Zero-based cell index",
                    },
                    "new_source": {"type": "string"},
                    "cell_type": {
                        "type": "string",
                        "description": "code, markdown, or raw",
                    },
                },
                "required": ["path", "cell_index", "new_source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show short git status for the workspace or a path inside it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to workspace (default .)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show git diff for the workspace or a specific file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "staged": {
                        "type": "boolean",
                        "description": "If true, show staged changes only",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill",
            "description": (
                "Load a workspace skill workflow by name. Returns instructions to follow "
                "using the listed tools. Use when a skill in the catalog matches the task."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Skill name from the Skills catalog",
                    },
                    "args": {
                        "type": "string",
                        "description": "Optional free-text arguments for the skill",
                    },
                },
                "required": ["skill_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_call",
            "description": (
                "Call a tool on a connected MCP server by server name and tool name. "
                "Prefer dedicated mcp__* tools when listed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string"},
                    "tool": {"type": "string"},
                    "arguments": {
                        "type": "object",
                        "description": "Tool arguments object",
                    },
                },
                "required": ["server", "tool"],
            },
        },
    },
]


def get_function_schemas(config: AgentConfig | None = None) -> list[dict[str, Any]]:
    """Built-in tools plus dynamic MCP tools, optionally filtered by an active skill."""
    schemas: list[dict[str, Any]] = list(FUNCTION_SCHEMAS)
    if config is not None:
        from ci2lab.harness.mcp.session import get_mcp_manager

        mgr = get_mcp_manager(config.cwd, connect=True)
        schemas.extend(mgr.build_function_schemas())
    if config is not None and config.skill_allowed_tools is not None:
        allowed = config.skill_allowed_tools
        schemas = [
            schema
            for schema in schemas
            if schema.get("function", {}).get("name") in allowed
        ]
    return schemas

_DISPATCH: dict[str, Callable[..., str]] = {
    "bash": lambda cfg, a: bash_tool.run_bash(
        cfg.cwd, a["command"], cfg.bash_timeout_seconds
    ),
    "read_file": lambda cfg, a: fs.read_file(
        cfg.cwd, a["path"], a.get("offset", 1), a.get("limit")
    ),
    "read_document": lambda cfg, a: fs.read_document(cfg.cwd, a["path"]),
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
    "todo_write": lambda cfg, a: todo_tool.todo_write(cfg.cwd, a["todos"]),
    "ask_user": lambda cfg, a: ask_user_tool.ask_user(
        a["question"],
        a.get("options"),
    ),
    "web_fetch": lambda cfg, a: web_tool.web_fetch(
        a["url"],
        a.get("max_chars", 80_000),
    ),
    "notebook_edit": lambda cfg, a: notebook_tool.notebook_edit(
        cfg.cwd,
        a["path"],
        a["cell_index"],
        a["new_source"],
        a.get("cell_type"),
    ),
    "git_status": lambda cfg, a: git_tools.git_status(cfg.cwd, a.get("path", ".")),
    "git_diff": lambda cfg, a: git_tools.git_diff(
        cfg.cwd,
        a.get("path"),
        a.get("staged", False),
    ),
    "skill": lambda cfg, a: skill_tool.invoke_skill(
        cfg,
        a["skill_name"],
        a.get("args"),
    ),
    "mcp_call": lambda cfg, a: _execute_mcp_call(
        cfg,
        a["server"],
        a["tool"],
        a.get("arguments") or {},
    ),
}


def _execute_mcp_call(
    config: AgentConfig,
    server: str,
    tool: str,
    arguments: dict[str, Any],
) -> str:
    from ci2lab.harness.mcp.session import get_mcp_manager

    mgr = get_mcp_manager(config.cwd, connect=True)
    return mgr.call(server, tool, arguments)


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
    from ci2lab.harness.mcp.session import get_mcp_manager
    from ci2lab.harness.permissions import check_permission

    name = call.name
    if not is_known_tool(name):
        return ToolResult(
            tool_name=name,
            content=f"Error: herramienta desconocida `{name}`",
            is_error=True,
            call_id=call.call_id,
        )

    if (
        config.skill_allowed_tools is not None
        and name not in config.skill_allowed_tools
        and name != "skill"
    ):
        return ToolResult(
            tool_name=name,
            content=(
                f"Error: tool `{name}` is not allowed by the active skill. "
                f"Allowed: {', '.join(sorted(config.skill_allowed_tools))}"
            ),
            is_error=True,
            call_id=call.call_id,
        )

    args = normalize_tool_arguments(call.arguments, tool_name=name)

    if name.startswith("mcp__"):
        mgr = get_mcp_manager(config.cwd, connect=True)
        output = mgr.call_by_id(name, args)
        is_error = output.startswith("Error:")
        if len(output) > config.max_tool_output_chars:
            output = (
                output[: config.max_tool_output_chars]
                + f"\n... (truncado, {len(output)} caracteres totales)"
            )
        return ToolResult(
            tool_name=name,
            content=output,
            is_error=is_error,
            call_id=call.call_id,
            outcome=outcome_for_tool_output(output) if is_error else None,
        )

    if name in WRITE_TOOLS:
        return _execute_write_tool(name, args, config, call.call_id)

    if name in {"skill", "mcp_call"}:
        try:
            output = _DISPATCH[name](config, args)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name=name,
                content=f"Error: {exc}",
                is_error=True,
                call_id=call.call_id,
            )
        is_error = output.startswith("Error:")
        return ToolResult(
            tool_name=name,
            content=output,
            is_error=is_error,
            call_id=call.call_id,
            outcome=outcome_for_tool_output(output) if is_error else None,
        )

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
