"""Tool name → implementation dispatch table.

Maps each canonical tool name to a handler ``lambda cfg, a: ...`` that unpacks
the validated argument dict ``a`` (and pulls run-scoped settings off the
:class:`~ci2lab.harness.types.AgentConfig` ``cfg``) before calling the concrete
tool implementation. The executor looks the handler up by name and invokes it;
every handler returns the tool's textual result.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ci2lab.harness.tools import ask_user as ask_user_tool
from ci2lab.harness.tools import bash as bash_tool
from ci2lab.harness.tools import calc as calc_tool
from ci2lab.harness.tools import convert as convert_tool
from ci2lab.harness.tools import docx as docx_tool
from ci2lab.harness.tools import filesystem as fs
from ci2lab.harness.tools import git_tools, skill_tool, vision_tool, yard_tool
from ci2lab.harness.tools import inspection as inspection_tool
from ci2lab.harness.tools import notebook as notebook_tool
from ci2lab.harness.tools import patch as patch_tool
from ci2lab.harness.tools import quiz as quiz_tool
from ci2lab.harness.tools import symcalc as symcalc_tool
from ci2lab.harness.tools import todo as todo_tool
from ci2lab.harness.tools import web as web_tool
from ci2lab.harness.types import AgentConfig

#: Canonical tool name -> handler. Each handler takes the run config and the
#: validated argument dict and returns the tool's textual result.
DISPATCH: dict[str, Callable[..., str]] = {
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
    "read_document": lambda cfg, a: fs.read_document(cfg.cwd, a["path"]),
    "create_quiz_questions": lambda cfg, a: quiz_tool.create_quiz_questions(
        cfg.cwd,
        a["path"],
        a["question_count"],
        a["difficulty"],
        a.get("options_per_question", quiz_tool.DEFAULT_OPTIONS_PER_QUESTION),
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
    "glob": lambda cfg, a: fs.glob_search(cfg.cwd, a["pattern"], a.get("path", ".")),
    "write_file": lambda cfg, a: fs.write_file(cfg.cwd, a["path"], a["content"]),
    "write_docx": lambda cfg, a: docx_tool.write_docx(cfg.cwd, a["path"], a["content"]),
    "apply_patch": lambda cfg, a: patch_tool.apply_patch(cfg.cwd, a["patch"]),
    "fill_docx_template": lambda cfg, a: _run_fill_docx(cfg, a),
    "docx_to_pdf": lambda cfg, a: convert_tool.docx_to_pdf(cfg.cwd, a["source"], a["output"]),
    "pdf_to_docx": lambda cfg, a: convert_tool.pdf_to_docx(cfg.cwd, a["source"], a["output"]),
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
        a.get("max_chars", 12_000),
    ),
    "web_search": lambda cfg, a: web_tool.web_search(
        a["query"],
        a.get("max_results", 5),
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
    "yard": lambda cfg, a: yard_tool.run_yard(
        cfg,
        a["action"],
        a.get("component"),
        a.get("entrypoint"),
        a.get("args"),
        a.get("query"),
    ),
    "delegate": lambda cfg, a: _run_delegate(cfg, a),
    "mcp_call": lambda cfg, a: execute_mcp_call(
        cfg,
        a["server"],
        a["tool"],
        a.get("arguments") or {},
    ),
    "analyze_image": lambda cfg, a: vision_tool.analyze_image_tool(
        a["path"],
        cfg,
        model_override=a.get("model", ""),
    ),
    "extract_visual_document": lambda cfg, a: vision_tool.extract_visual_document_tool(
        a["path"],
        cfg,
    ),
    "calc": lambda cfg, a: calc_tool.calc(a["expression"]),
    "symcalc": lambda cfg, a: symcalc_tool.symcalc(a["expression"]),
}


def execute_mcp_call(
    config: AgentConfig,
    server: str,
    tool: str,
    arguments: dict[str, Any],
) -> str:
    """Invoke a tool exposed by a connected MCP server.

    Args:
        config: Active agent configuration; its ``cwd`` scopes the MCP manager.
        server: Name of the configured MCP server to route the call to.
        tool: Name of the tool to invoke on that server.
        arguments: Argument mapping forwarded to the remote tool.

    Returns:
        The textual result returned by the MCP server.
    """
    from ci2lab.harness.mcp.session import get_mcp_manager

    mgr = get_mcp_manager(config.cwd, connect=True)
    return mgr.call(server, tool, arguments)


def _run_delegate(config: AgentConfig, args: dict[str, Any]) -> str:
    """Run a sub-agent delegation, defaulting to ``explore`` mode."""
    from ci2lab.harness.tools.delegate import run_delegation

    return run_delegation(
        config,
        str(args.get("task", "")),
        str(args.get("mode", "explore") or "explore"),
    )


def _run_fill_docx(config: AgentConfig, args: dict[str, Any]) -> str:
    """Fill a .docx template, coercing template/output/fields to strings."""
    from ci2lab.harness.tools.docx_writer import fill_docx_template

    return fill_docx_template(
        cwd=config.cwd,
        template=str(args.get("template", "")),
        output=str(args.get("output", "")),
        fields={str(k): str(v) for k, v in (args.get("fields") or {}).items()},
    )
