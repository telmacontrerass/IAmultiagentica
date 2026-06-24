"""ArgumentParser and global CLI help."""

from __future__ import annotations

import argparse

_CLI_COMMANDS = frozenset(
    {
        "agent",
        "chat",
        "sessions",
        "doctor",
        "hardware",
        "models",
        "evals",
        "skills",
        "permissions",
        "ui",
        "tools",
        "menu",
    }
)


def _is_global_help_request(raw_argv: list[str]) -> bool:
    """True when the user asks for global help with no subcommand."""
    if not raw_argv:
        return True
    return raw_argv in (["--help"], ["-h"])


def _print_global_help() -> None:
    """Global ASCII help (cp1252-compatible)."""
    lines = [
        "usage: ci2lab [options] [command] [arguments]",
        "",
        "Local CLI: detects hardware, recommends models and runs an agent",
        "with tools in the terminal (read, grep, bash, supervised editing).",
        "",
        "Shortcut:",
        '  ci2lab "request"                  Run the agent (same as agent)',
        "",
        "Main commands:",
        '  ci2lab agent "request"            One task and exit',
        "  ci2lab chat                       Interactive mode (REPL)",
        "  ci2lab menu                       Open the interactive launcher",
        "  ci2lab --multi-agent chat         REPL with subagent orchestrator",
        "  ci2lab tools qwen:1.8b            Simple chat with tools",
        "  ci2lab qwen:1.8b tools            Same thing, short form",
        "  ci2lab sessions [--json]          List saved sessions",
        "  ci2lab skills [--json]            List available built-in/user/workspace skills",
        "  ci2lab doctor                     Check Python, Ollama and models",
        "  ci2lab hardware [--json]          RAM, GPU, memory budget",
        "  ci2lab models recommend [query]",
        "                                    Recommended models for your PC",
        "  ci2lab models install <model>     pull/run/chat commands for a model",
        "  ci2lab models run <model>         Open the model with ollama run",
        "  ci2lab evals run                  Harness evaluations (mock)",
        "  ci2lab permissions summary        Permissions / audit dashboard",
        "  ci2lab ui                         Local web interface",
        "",
        "Agent flags (shortcut, agent and chat):",
        "  --model TAG                       Ollama tag (e.g. qwen2.5-coder:7b)",
        "  --tool-mode {native,fenced}       native=function calling; fenced=blocks",
        "  --workspace PATH                  Agent working directory",
        "  --cwd PATH                        Legacy alias of --workspace",
        "  --yes                             Auto-confirm bash (does not skip preview)",
        "  --security-engine ENGINE          Engine: claude_experimental (default),",
        "                                    ci2lab (legacy), opencode_experimental (lab)",
        "  --no-stream                       Disable token streaming",
        "  --max-rounds N                    Maximum agent rounds",
        "  --multi-agent                     Use the sequential subagent orchestrator",
        "  --session ID                      Resume session in chat/agent",
        "  --runs-dir PATH                   Logs directory (default: runs)",
        "  --no-log                          Do not save artifacts in runs/",
        "  --image PATH                      Attach an image (PNG/JPG/WEBP/BMP).",
        "                                    Repeat for multiple images.",
        "                                    Requires a vision model (e.g. qwen2.5vl:7b).",
        "",
        "Important: agent flags go BEFORE the subcommand:",
        "  ci2lab --model qwen2.5-coder:7b --tool-mode fenced chat",
        "",
        "Per-command options:",
        "  models recommend [--json] [--limit N] [query]",
        "  models install <id|tag> [--json]",
        "  models run <id|tag>",
        "  evals run [--live] [--model TAG] [--task ID] [--tasks-dir PATH]",
        "",
        "Evals (alternative):",
        "  python -m ci2lab.evals.run        Same as ci2lab evals run (mock)",
        "",
        "Agent tools (inside chat/agent):",
        "  read_document, read_file, ls, glob, grep, edit_file, write_file, notebook_edit,",
        "  bash, git_status, git_diff, todo_write, ask_user, web_search, web_fetch",
        "  (if you ask for live info with no URL: web_search first, then web_fetch to read sources)",
        "",
        "Optional config: ci2lab.yaml or ~/.ci2lab/ci2lab.yaml",
        "  (model, workspace, runs_dir, write_tools_enabled, etc.)",
        "",
        "Detailed help per command:",
        "  ci2lab <command> --help",
        "  ci2lab models recommend --help",
        "",
        "Ejemplos modo multiagente:",
        "  ci2lab agent --multi-agent --model mistral:7b chat",
        "  ci2lab agent --multi-agent --model llama3.1:8b chat",
        "  ci2lab agent --multi-agent --model qwen2.5-coder:14b chat",
    ]
    print("\n".join(lines))


def _add_agent_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--model",
        default=None,
        help="Ollama tag (override; otherwise config or CI2LAB_MODEL)",
    )
    p.add_argument(
        "--tool-mode",
        choices=["native", "fenced"],
        default=None,
        help="Tool invocation mode",
    )
    p.add_argument(
        "--cwd",
        default=None,
        help="Working directory (legacy; prefer --workspace)",
    )
    p.add_argument(
        "--workspace",
        default=None,
        help="Agent working directory (semantic alias of --cwd)",
    )
    p.add_argument("--yes", action="store_true", help="Auto-confirm dangerous tools")
    from ci2lab.security.engine import CLI_SECURITY_ENGINE_CHOICES

    p.add_argument(
        "--security-engine",
        choices=list(CLI_SECURITY_ENGINE_CHOICES),
        default=None,
        metavar="ENGINE",
        help=(
            "Security engine (default: claude_experimental). "
            "ci2lab=legacy without deny/ask/allow; opencode_experimental=unsafe lab."
        ),
    )
    p.add_argument("--no-stream", action="store_true", help="Disable token streaming")
    p.add_argument("--max-rounds", type=int, default=None)
    p.add_argument(
        "--multi-agent",
        action="store_true",
        help="Use the sequential subagent orchestrator for one task",
    )
    p.add_argument("--session", default=None, help="Session ID (new one if omitted in REPL)")
    p.add_argument(
        "--runs-dir",
        default=None,
        help="Base directory for run logs (default: runs)",
    )
    p.add_argument(
        "--no-log",
        action="store_true",
        help="Do not save run artifacts in runs/",
    )
    p.add_argument(
        "--image",
        action="append",
        dest="images",
        default=None,
        metavar="PATH",
        help=(
            "Image or scanned-PDF file to attach. "
            "Only image-only (scanned) PDFs are rendered to pages; "
            "text PDFs should be read via read_document in the prompt. "
            "Repeat to attach multiple files. "
            "Requires a vision-capable model (e.g. --model qwen2.5vl:7b)."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ci2lab",
        description="Local multi-model agent with an agentic harness",
    )
    _add_agent_flags(parser)

    sub = parser.add_subparsers(dest="command")

    agent_p = sub.add_parser("agent", help="One request and exit")
    agent_p.add_argument("agent_prompt", help="Request for the agent")
    _add_agent_flags(agent_p)

    sub.add_parser("chat", help="Interactive REPL mode").set_defaults(command="chat")
    sub.add_parser("menu", help="Open the interactive launcher").set_defaults(command="menu")

    sessions_p = sub.add_parser("sessions", help="List saved sessions")
    sessions_p.add_argument("--json", action="store_true")

    skills_p = sub.add_parser("skills", help="List available skills")
    skills_p.add_argument("--json", action="store_true")

    sub.add_parser("doctor", help="Check environment")

    hardware_p = sub.add_parser("hardware", help="Detect the computer's characteristics")
    hardware_p.add_argument("--json", action="store_true", help="Show output as JSON")

    models_p = sub.add_parser("models", help="Work with local models")
    models_sub = models_p.add_subparsers(dest="models_command", required=True)
    recommend_p = models_sub.add_parser("recommend", help="Recommend models to download")
    recommend_p.add_argument("model_prompt", nargs="*", help="Optional specific query")
    recommend_p.add_argument("--json", action="store_true", help="Show output as JSON")
    recommend_p.add_argument("--limit", type=int, default=5, help="Maximum number of models")
    install_p = models_sub.add_parser(
        "install",
        help="Show the command to install and open an allowed model",
    )
    install_p.add_argument("model", help="Catalog ID or Ollama tag")
    install_p.add_argument("--json", action="store_true", help="Show output as JSON")
    run_p = models_sub.add_parser(
        "run",
        help="Open the model in the console with ollama run",
    )
    run_p.add_argument("model", help="Catalog ID or Ollama tag")

    evals_p = sub.add_parser("evals", help="Practical harness evaluation")
    evals_sub = evals_p.add_subparsers(dest="evals_command")
    evals_run = evals_sub.add_parser("run", help="Run tasks from evals/")
    evals_run.add_argument("--tasks-dir", default=None)
    evals_run.add_argument("--task", action="append", dest="task_ids", metavar="ID")
    evals_run.add_argument("--model", default=None)
    evals_run.add_argument("--live", action="store_true")

    from ci2lab.cli_permissions import add_permissions_parser

    add_permissions_parser(sub)

    ui_p = sub.add_parser("ui", help="Local web interface")
    ui_p.add_argument("--host", default="127.0.0.1", help="Local host")
    ui_p.add_argument("--port", type=int, default=8765, help="Local port")
    ui_p.add_argument("--no-open", action="store_true", help="Do not open browser")

    return parser
