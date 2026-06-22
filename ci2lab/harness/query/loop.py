"""
ReAct loop of the agentic harness.

Per round:
  1. Trim history to the model context
  2. Call the LLM (optional streaming)
  3. Detect tool calls (native, XML, or fenced)
  4. Execute tools -> append results
  5. Repeat until a tool-free answer or max_rounds

The loop is task-agnostic: it has no per-topic special cases. Robustness comes
from a small set of general mechanisms — loop detection, an error-streak cutoff,
workspace-policy handling, edit follow-ups, and a few recovery nudges — all of
which apply to any task.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

from ci2lab.console import console
from ci2lab.contracts.types import HardwareProfile, ModelSelection
from ci2lab.harness.context import manage_context, trim_messages
from ci2lab.harness.edit_followup import EditSignature, process_edit_round
from ci2lab.harness.hooks import emit_hook_event
from ci2lab.harness.llm_client import LLMClient
from ci2lab.harness.llm_errors import LLMCancelledError, LLMError, classify_request_error
from ci2lab.harness.messages import append_assistant_turn, append_tool_results
from ci2lab.harness.mcp.session import close_mcp_manager
from ci2lab.harness.parsing import (
    looks_like_unparsed_tool_attempt,
    resolve_tool_calls,
    strip_tool_markup,
)
from ci2lab.harness.prompts import build_system_prompt
from ci2lab.harness.query.llm_io import call_llm
from ci2lab.harness.query.nudges import (
    summarize_args,
    web_fetch_failed_nudge,
)
from ci2lab.harness.query.retry_governor import (
    ERROR_CLASS_LIMIT,
    MAX_SAME_CALL,
    error_class_key,
)
from ci2lab.harness.query.session_hooks import maybe_save_session
from ci2lab.harness.run_logger import RunLogger
from ci2lab.harness.session import delete_session, is_delete_session_request, load_session
from ci2lab.harness.security.policy import (
    POLICY_NUDGE_MESSAGE,
    POLICY_REPEAT_MESSAGE,
    is_policy_error,
    tool_call_signature,
)
from ci2lab.harness.tools.registry import execute_tool, get_function_schemas
from ci2lab.harness.tools.todo import todo_read
from ci2lab.harness.token_usage import format_token_usage_line
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult

_EXPLICIT_URL_RE = re.compile(r"https?://\S+")

# The USER (not the harness) telling the agent to stop using tools and answer
# now. Computed once from the user's own prompt, never from harness-injected
# messages, so the loop-break nudge below can never trip it.
_STOP_TOOLS_RE = re.compile(
    r"(answer with what you (already )?(know|have)|"
    r"reply with what you (already )?have|"
    r"stop searching|don'?t keep searching|just answer)",
    re.IGNORECASE,
)
# A model claiming it has no internet access, so we can remind it about web tools.
_NO_INTERNET_RE = re.compile(
    r"(i (do not|don'?t) have (access to )?(the )?internet|"
    r"i can'?t (search|access) the web)",
    re.IGNORECASE,
)

_LOOP_BREAK_NUDGE = (
    "You keep calling the same tool with the same arguments. Its result is "
    "already in the conversation above, so repeating it does not help. Do not "
    "call it again. If the task still has remaining steps, do the NEXT step now "
    "(for example: write the file, edit the code, or run the check). If a tool "
    "is blocked by the skill, use an allowed equivalent (`ls`, `grep`, `glob`, "
    "`read_file`). Only give a final answer once every step of the request is "
    "complete; if it cannot be completed, say so plainly.\n\n"
    "Original request: {user_prompt}"
)
_LOOP_GIVE_UP = (
    "I could not complete the task: the same tool repeated without making "
    "progress. Check the last error shown above (skill permissions, a wrong "
    "path, or a format issue)."
)
_ERROR_STREAK_GIVE_UP = (
    "I could not complete the task: the tools failed repeatedly. Last error: "
    "{error}"
)
_GOVERNOR_REPEAT_MESSAGE = (
    "This exact call already failed repeatedly. Do not run it again. Use a "
    "different tool, different arguments, or stop and explain the blocker."
)
_GOVERNOR_GIVE_UP = (
    "I could not complete the task: `{tool}` kept failing ({error_class}). "
    "Last error: {error}\n"
    "Try a different approach, or the task may not be doable as requested."
)
_STOP_TOOLS_NUDGE = (
    "Do not use tools. Answer now with what you have, and add a short warning if "
    "some sources are missing."
)
_WEB_CAPABILITY_NUDGE = (
    "You can use `web_search` for live info without a URL, then `web_fetch` for "
    "selected sources."
)
_UNPARSED_FENCED_HINT = (
    "Your previous tool call was not executed. Use a fenced block with the tool "
    "name as the tag, e.g.\n"
    "```write_file\n"
    '{"path": "file.py", "content": "..."}\n'
    "```\n"
    "Do not put write_file inside a bash block. Do not reply with plain JSON only."
)
_UNPARSED_NATIVE_HINT = (
    "Your previous tool call was not executed. Invoke the tool through function "
    "calling, or use a ```write_file fenced block with JSON arguments."
)
_ALREADY_RETRIEVED_MESSAGE = (
    "Already retrieved earlier in this turn — its result is in the conversation "
    "above. Not running it again. Use that result and continue with the next "
    "step of the task; if every step is already done, give the final answer."
)
_DESCRIBED_NOT_WRITTEN_NUDGE = (
    "You described the change in prose but did not apply it — nothing was written "
    "to disk. The request needs a file created or edited, so call `write_file` "
    "(or `edit_file`) now with the full content. Do not just show the code as "
    "text; actually write it."
)

# Read-only tools whose result for a given argument set does not change within a
# turn unless a mutating tool runs. Re-calling them is pure waste and only bloats
# the context, so the loop serves a cached note instead of re-executing.
_READ_ONLY_TOOLS = frozenset({
    "read_document",
    "read_file",
    "ls",
    "tree",
    "glob",
    "grep",
    "file_info",
    "inspect_file",
})
# Tools that can change the workspace; running any of them invalidates the
# read-only cache so a later re-read reflects the new state.
_MUTATING_TOOLS = frozenset({
    "write_file",
    "edit_file",
    "apply_patch",
    "notebook_edit",
    "bash",
    "write_docx",
    "docx_to_pdf",
    "pdf_to_docx",
})
# The user's current prompt explicitly asks to create or change something. Used
# only to nudge once when the model narrates a change without ever applying it.
_WRITE_INTENT_RE = re.compile(
    r"\b(write|create|implement|add|edit|modify|fix)\w*",
    re.IGNORECASE,
)


def _read_signature(call: ToolCall) -> str:
    return f"{call.name}:{hashlib.md5(str(call.arguments).encode()).hexdigest()[:8]}"


def _status(label: str) -> None:
    console.print(f"[dim italic cyan]{label}[/dim italic cyan]")


def _emit_progress(
    label: str,
    on_progress: Callable[[str], None] | None,
) -> None:
    if on_progress:
        on_progress(label)
        return
    if not label:
        return
    _status(label)


def _raise_if_cancelled(cfg: AgentConfig) -> None:
    event = cfg.cancellation_event
    if event is not None and event.is_set():
        raise LLMCancelledError()


def _initial_progress_label(user_prompt: str) -> str:
    """Describe the first model round in user-friendly terms."""
    text = user_prompt.lower()
    if any(word in text for word in ("pdf", "docx", "document", "documento")):
        return "Preparing to read the document..."
    if any(
        word in text
        for word in ("web", "internet", "latest", "current", "hoy", "actual")
    ):
        return "Checking what information is needed..."
    if re.search(
        r"\b(code|codigo|código|test|prueba|bug|fix|implement|implementa|"
        r"arregla|corrige|modifica|cambia)\b",
        text,
    ):
        return "Planning the code change..."
    if re.search(
        r"\b(repo|repository|repositorio|project|proyecto|file|files|"
        r"archivo|archivos|carpeta|directorio)\b",
        text,
    ):
        return "Inspecting the relevant project context..."
    return "Deciding the next step..."


def _model_progress_label(user_prompt: str, round_num: int) -> str:
    """Describe what the model is doing before each LLM call."""
    if round_num == 1:
        return _initial_progress_label(user_prompt)
    return "Reviewing the latest results and deciding the next step..."


def _path_looks_like_pdf(path: Any) -> bool:
    return str(path or "").lower().endswith(".pdf")


def _tool_progress_label(calls: list[ToolCall]) -> str:
    """Describe the real tool work about to run without exposing tool internals."""
    names = {call.name for call in calls}
    if names & {"docx_to_pdf", "pdf_to_docx"}:
        return "Converting the document..."
    if any(
        call.name in {"read_document", "read_file"}
        and _path_looks_like_pdf(call.arguments.get("path") or call.arguments.get("source"))
        for call in calls
    ):
        return "Extracting information from the PDF..."
    if names & {"read_document"}:
        return "Reading the document..."
    if names & {"write_file", "edit_file", "apply_patch", "notebook_edit"}:
        return "Generating code changes..."
    if names & {"web_search", "web_fetch"}:
        return "Looking up current information..."
    if names & {"ls", "tree", "glob", "grep", "file_info", "inspect_file", "read_file"}:
        return "Searching the project files..."
    if names & {"bash"}:
        return "Running the requested check..."
    if names & {"todo_write"}:
        return "Updating the task plan..."
    if any(name == "skill" or name == "mcp_call" or name.startswith("mcp__") for name in names):
        return "Using the selected integration..."
    return "Running the next step..."


def _todo_plan_snippet(cwd: str) -> str:
    """A compact, current view of the workspace task plan, or "" if none.

    Re-surfacing the plan keeps a long multi-step task oriented for far fewer
    tokens than restating the whole prompt, and it survives compaction because
    `todo_write`/`todo_read` results are not compactable.
    """
    raw = todo_read(cwd)
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(items, list) or not items:
        return ""
    lines = [
        f"  [{item.get('status', 'pending')}] {item.get('content', '')}".rstrip()
        for item in items
        if isinstance(item, dict)
    ]
    if not lines:
        return ""
    return "Current task plan (keep it updated with `todo_write`):\n" + "\n".join(lines)


def _current_request_anchor(user_prompt: str, cwd: str) -> dict[str, Any]:
    plan = _todo_plan_snippet(cwd)
    plan_block = f"\n\n{plan}" if plan else ""
    return {
        "role": "user",
        "_anchor": True,
        "content": (
            "The user's current request is:\n"
            f"{user_prompt}\n\n"
            "Finish this request fully, including any file/tool-output "
            "instructions it depends on. Do not resume an unrelated earlier task."
            f"{plan_block}"
        ),
    }


def _role_anchor_message(role_anchor: str) -> dict[str, Any]:
    """Wrap a subagent role anchor as a user message for reinjection."""
    return {
        "role": "user",
        "_anchor": True,
        "content": (
            f"{role_anchor}\n\n"
            "Continue within this subagent role. Use the tool results already "
            "available and do not switch responsibilities."
        ),
    }
def _strip_anchors(history: list[dict[str, Any]]) -> None:
    """Remove every anchor message from history, in place.

    Anchors are re-appended fresh each round; clearing the prior round's first
    means history holds at most one anchor pair instead of accumulating one full
    copy of the prompt (+ role boilerplate) per round — the dominant context
    leak on long multi-step tasks. Anchors are synthetic user messages appended
    after tool results, so dropping them never breaks tool_call/result pairing.
    """
    history[:] = [m for m in history if not m.get("_anchor")]


def _print_model_step(content: str, *, already_streamed: bool) -> None:
    """Show non-tool text from a model round before executing tools."""
    display = strip_tool_markup(content).strip()
    if not display or already_streamed:
        return
    console.print(f"[dim]Model:[/dim] {display}")


def _redirect_fetch_to_search(
    calls: list[ToolCall],
    user_prompt: str,
    web_search_used: bool,
) -> list[ToolCall]:
    """Replace web_fetch with web_search when the model invented a URL.

    If web_search hasn't run yet AND the user didn't supply an explicit URL in
    their prompt, redirect every web_fetch call to web_search so the model
    discovers the correct URL rather than guessing one from memory.
    """
    if web_search_used:
        return calls
    user_urls = set(_EXPLICIT_URL_RE.findall(user_prompt))
    redirected: list[ToolCall] = []
    changed = False
    for call in calls:
        if call.name == "web_fetch":
            url = str(call.arguments.get("url", ""))
            if url not in user_urls:
                redirected.append(
                    ToolCall(
                        name="web_search",
                        arguments={"query": user_prompt, "max_results": 5},
                        call_id=call.call_id,
                    )
                )
                changed = True
                continue
        redirected.append(call)
    if changed:
        console.print(
            "[yellow]web_fetch redirected to web_search "
            "(the model invented a URL; searching first).[/yellow]"
        )
    return redirected


def _prepend_missing_reads(calls: list[ToolCall], user_prompt: str) -> list[ToolCall]:
    """Read an edited file first when the user explicitly requested that sequence."""
    if not calls or not re.search(r"\bread\b", user_prompt, re.IGNORECASE):
        return calls
    edit_paths = {
        str(call.arguments["path"])
        for call in calls
        if call.name == "edit_file" and call.arguments.get("path")
    }
    read_paths = {
        str(call.arguments["path"])
        for call in calls
        if call.name in {"read_file", "read_document"} and call.arguments.get("path")
    }
    missing = sorted(edit_paths - read_paths)
    if not missing:
        return calls
    prefixed = [
        ToolCall(
            name="read_file",
            arguments={"path": path},
            call_id=f"call_{uuid.uuid4().hex[:8]}",
        )
        for path in missing
    ]
    return prefixed + calls


def run_agent(
    user_prompt: str,
    selection: ModelSelection,
    *,
    hardware: HardwareProfile | None = None,  # noqa: ARG001
    config: AgentConfig | None = None,
    messages: list[dict[str, Any]] | None = None,
    on_round: Callable[[int, str], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    cfg = config or AgentConfig(cwd=".")
    cfg.token_usage.reset_turn()
    if cfg.session_id:
        stored_session = load_session(cfg.session_id)
        if stored_session:
            cfg.token_usage.hydrate_session(stored_session.get("token_usage"))
    if cfg.session_id and is_delete_session_request(user_prompt):
        deleted = delete_session(cfg.session_id)
        final_text = (
            f"Session {cfg.session_id} deleted."
            if deleted
            else "There was no saved session to delete."
        )
        console.print(final_text)
        return final_text

    client = LLMClient(selection)
    system = build_system_prompt(selection, cfg.cwd)

    if messages is None:
        history: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
    else:
        history = list(messages)
        if not any(m.get("role") == "system" for m in history):
            history.insert(0, {"role": "system", "content": system})
        history.append({"role": "user", "content": user_prompt})

    # Read once from the user's own words; harness nudges never change this.
    stop_tools_requested = bool(_STOP_TOOLS_RE.search(user_prompt))

    recent_sigs: deque[str] = deque(maxlen=6)
    policy_blocked_sigs: set[str] = set()
    # Retry governor: bound repeated failures (Phase 2).
    failed_call_sigs: dict[str, int] = {}      # exact call -> error count
    error_class_counts: dict[str, int] = {}    # tool::error_class -> count
    error_class_last: dict[str, str] = {}      # tool::error_class -> last error text
    policy_nudge_sent = False
    stuck_rounds = 0
    stuck_nudges = 0
    error_streak = 0
    unparsed_tool_nudges = 0
    summary_failures = 0
    web_search_used = False  # becomes True once web_search runs in this turn
    web_capability_nudge_sent = False
    stop_tools_nudge_sent = False
    described_not_written_nudge_sent = False
    # Per-turn cache of successful read-only calls (signature -> True). A
    # mutating tool clears it so later re-reads reflect the new workspace state.
    satisfied_reads: set[str] = set()
    # Any mutating tool was *attempted* this turn (even if blocked/denied). Used
    # only to suppress the "describe but don't write" nudge — if the model
    # already tried to write, re-nudging it is pointless.
    attempted_write_this_turn = False
    write_intent = bool(_WRITE_INTENT_RE.search(user_prompt))
    completed_edits: set[EditSignature] = set()
    final_text = ""
    content = ""
    status = "success"
    log_error: str | None = None
    # Real token counters (filled in by Ollama after each LLM call).
    tokens_prompt_last: int = 0       # prompt_tokens from the last round
    tokens_prompt_peak: int = 0       # max prompt_tokens seen in any round
    tokens_completion_total: int = 0  # accumulated completion_tokens (real output)

    run_log = RunLogger.maybe_create(cfg, selection, user_prompt)
    if run_log:
        run_log.start()

    try:
        for round_num in range(1, cfg.max_rounds + 1):
            _raise_if_cancelled(cfg)
            console.print(f"[dim]── Round {round_num} ──[/dim]")
            if run_log:
                run_log.set_rounds_completed(round_num)
            streamed_this_round = False

            history, summary_failures, compact_events = manage_context(
                history,
                client,
                selection.context_length,
                summary_failures=summary_failures,
            )
            for event in compact_events:
                console.print(f"[dim]{event}[/dim]")

            content = ""
            calls: list[ToolCall] = []

            trimmed = trim_messages(history, selection.context_length)
            tools = (
                get_function_schemas(cfg)
                if selection.supports_tools and not stop_tools_requested
                else None
            )
            web_search_available = bool(
                tools
                and any(
                    (t.get("function") or {}).get("name") == "web_search"
                    for t in tools
                )
            )
            # Avoid leaking provisional model prose before tool execution.
            # When tools are available, parse first and only render final text.
            stream_this_round = cfg.stream and not bool(tools)
            _emit_progress(
                _model_progress_label(user_prompt, round_num),
                on_progress,
            )
            _raise_if_cancelled(cfg)
            streamed_this_round = stream_this_round
            try:
                llm_response = call_llm(
                    client,
                    trimmed,
                    tools=tools,
                    stream=stream_this_round,
                    cancel_event=cfg.cancellation_event,
                )
            except LLMError as exc:
                status = "llm_error"
                log_error = exc.user_message
                maybe_save_session(cfg, history, selection)
                raise
            except Exception as exc:  # noqa: BLE001
                err = classify_request_error(
                    exc, model=selection.ollama_tag, url=client.chat_url
                )
                console.print(f"[red]{err.user_message}[/red]")
                status = "llm_error"
                log_error = err.user_message
                maybe_save_session(cfg, history, selection)
                raise err from exc

            content = llm_response.content or ""
            _raise_if_cancelled(cfg)
            usage = llm_response.usage
            cfg.token_usage.record_call(usage)
            if usage and usage.available:
                tokens_prompt_last = usage.prompt_tokens
                tokens_completion_total += usage.completion_tokens
                if usage.prompt_tokens > tokens_prompt_peak:
                    tokens_prompt_peak = usage.prompt_tokens
            if run_log:
                run_log.record_token_usage(round_num=round_num, usage=usage)
            if on_round:
                on_round(round_num, content)

            calls = resolve_tool_calls(
                content,
                llm_response.tool_calls,
                tool_mode=selection.tool_mode,
            )
            if stop_tools_requested:
                calls = []
            calls = _prepend_missing_reads(calls, user_prompt)
            calls = _redirect_fetch_to_search(calls, user_prompt, web_search_used)
            if calls:
                _print_model_step(content, already_streamed=streamed_this_round)
                # Do not keep free-form model text before the real tool result.
                content = ""

            if not calls:
                if (
                    stop_tools_requested
                    and not (strip_tool_markup(content).strip() or content.strip())
                    and not stop_tools_nudge_sent
                ):
                    stop_tools_nudge_sent = True
                    append_assistant_turn(history, content)
                    history.append({"role": "user", "content": _STOP_TOOLS_NUDGE})
                    maybe_save_session(cfg, history, selection)
                    continue

                if (
                    looks_like_unparsed_tool_attempt(content)
                    and unparsed_tool_nudges < 2
                    and selection.supports_tools
                ):
                    unparsed_tool_nudges += 1
                    console.print(
                        "[yellow]Tool call detected as text but not executed; "
                        "asking the model to retry.[/yellow]"
                    )
                    append_assistant_turn(history, content)
                    hint = (
                        _UNPARSED_FENCED_HINT
                        if selection.tool_mode == "fenced"
                        else _UNPARSED_NATIVE_HINT
                    )
                    history.append({"role": "user", "content": hint})
                    maybe_save_session(cfg, history, selection)
                    continue

                final_text = strip_tool_markup(content).strip() or content.strip()
                if (
                    final_text
                    and web_search_available
                    and not web_capability_nudge_sent
                    and _NO_INTERNET_RE.search(final_text)
                ):
                    web_capability_nudge_sent = True
                    append_assistant_turn(history, final_text or content)
                    history.append({"role": "user", "content": _WEB_CAPABILITY_NUDGE})
                    maybe_save_session(cfg, history, selection)
                    continue
                # The user asked to create/change something, the model is about to
                # finalize with only prose, and nothing was ever written this turn.
                # Nudge once to actually apply the change instead of describing it.
                if (
                    final_text
                    and write_intent
                    and not attempted_write_this_turn
                    and not described_not_written_nudge_sent
                    and selection.supports_tools
                    and not stop_tools_requested
                ):
                    described_not_written_nudge_sent = True
                    console.print(
                        "[yellow]Change described but never written; asking the "
                        "model to apply it.[/yellow]"
                    )
                    append_assistant_turn(history, final_text or content)
                    history.append(
                        {"role": "user", "content": _DESCRIBED_NOT_WRITTEN_NUDGE}
                    )
                    maybe_save_session(cfg, history, selection)
                    continue
                _emit_progress("Finalizing the answer...", on_progress)
                _emit_progress("", on_progress)
                if final_text and streamed_this_round:
                    console.print()
                elif final_text:
                    console.print(final_text)
                append_assistant_turn(history, final_text or content)
                maybe_save_session(cfg, history, selection)
                break

            sig = "|".join(
                f"{c.name}:{hashlib.md5(str(c.arguments).encode()).hexdigest()[:8]}"
                for c in calls
            )
            if any(c.name == "web_search" for c in calls):
                web_search_used = True
            if sig in recent_sigs:
                stuck_rounds += 1
            else:
                stuck_rounds = 0
            recent_sigs.append(sig)

            if stuck_rounds >= 2:
                stuck_nudges += 1
                if stuck_nudges > 2:
                    console.print(
                        "[yellow]Persistent loop; stopping and answering with "
                        "what is available.[/yellow]"
                    )
                    status = "stuck"
                    final_text = strip_tool_markup(content).strip() or _LOOP_GIVE_UP
                    console.print(final_text)
                    append_assistant_turn(history, final_text)
                    maybe_save_session(cfg, history, selection)
                    break
                console.print("[yellow]Loop detected; asking for a final answer.[/yellow]")
                history.append({
                    "role": "user",
                    "content": _LOOP_BREAK_NUDGE.format(user_prompt=user_prompt),
                })
                continue

            append_assistant_turn(history, content, calls)
            results = []
            round_policy_error = False
            _emit_progress(_tool_progress_label(calls), on_progress)
            for call in calls:
                _raise_if_cancelled(cfg)
                console.print(f"[cyan]▶ {call.name}[/cyan] {summarize_args(call.arguments)}")
                started_at = datetime.now(timezone.utc)
                psig = tool_call_signature(call)
                for warning in emit_hook_event(
                    cfg,
                    "before_tool",
                    {
                        "tool": call.name,
                        "arguments": call.arguments,
                        "round": round_num,
                    },
                ):
                    console.print(f"[yellow]{warning}[/yellow]")
                rsig = _read_signature(call)
                if (
                    call.name in _READ_ONLY_TOOLS
                    and rsig in satisfied_reads
                    and psig not in policy_blocked_sigs
                ):
                    # Identical read-only call already succeeded this turn and
                    # nothing has mutated the workspace since. Re-running only
                    # re-injects the same content and stalls progress, so serve a
                    # short note pointing the model to the next step instead.
                    result = ToolResult(
                        tool_name=call.name,
                        content=_ALREADY_RETRIEVED_MESSAGE,
                        is_error=False,
                        call_id=call.call_id,
                        outcome="already_satisfied",
                    )
                elif psig in policy_blocked_sigs:
                    result = ToolResult(
                        tool_name=call.name,
                        content=POLICY_REPEAT_MESSAGE,
                        is_error=True,
                        call_id=call.call_id,
                        outcome="blocked_by_policy",
                    )
                elif failed_call_sigs.get(psig, 0) >= MAX_SAME_CALL:
                    # This exact call already failed repeatedly; do not run it
                    # again — force the model to change tack.
                    result = ToolResult(
                        tool_name=call.name,
                        content=_GOVERNOR_REPEAT_MESSAGE,
                        is_error=True,
                        call_id=call.call_id,
                        outcome="repeated_failure",
                    )
                else:
                    result = execute_tool(call, cfg)
                    if is_policy_error(result):
                        policy_blocked_sigs.add(psig)
                        round_policy_error = True
                for warning in emit_hook_event(
                    cfg,
                    "after_tool",
                    {
                        "tool": call.name,
                        "arguments": call.arguments,
                        "round": round_num,
                        "ok": not result.is_error,
                        "outcome": result.outcome,
                        "output": str(result.content)[:1000],
                    },
                ):
                    console.print(f"[yellow]{warning}[/yellow]")
                # Maintain the read-only cache: a successful mutation invalidates
                # it; a successful read populates it.
                if call.name in _MUTATING_TOOLS:
                    attempted_write_this_turn = True
                    if not result.is_error:
                        satisfied_reads.clear()
                if not result.is_error and call.name in _READ_ONLY_TOOLS:
                    satisfied_reads.add(rsig)
                if result.is_error and result.outcome != "blocked_by_policy":
                    failed_call_sigs[psig] = failed_call_sigs.get(psig, 0) + 1
                    eclass = error_class_key(call, result)
                    error_class_counts[eclass] = error_class_counts.get(eclass, 0) + 1
                    error_class_last[eclass] = result.content
                ended_at = datetime.now(timezone.utc)
                if run_log:
                    run_log.record_tool_call(
                        round_num=round_num,
                        call=call,
                        result=result,
                        started_at=started_at,
                        ended_at=ended_at,
                    )
                if result.is_error:
                    console.print(f"[red]  ✗ {result.content[:200]}[/red]")
                else:
                    preview = result.content[:120].replace("\n", " ")
                    console.print(f"[green]  ✓[/green] {preview}...")
                results.append(result)

            append_tool_results(history, results)
            # Keep only the freshest anchors: drop the previous round's before
            # re-appending, so the prompt is restated once, not once per round.
            _strip_anchors(history)
            if cfg.role_anchor:
                history.append(_role_anchor_message(cfg.role_anchor))
            history.append(_current_request_anchor(user_prompt, cfg.cwd))

            # Error-streak cutoff: even when arguments change each round (so the
            # signature detector does not see a loop), if every tool fails for
            # several rounds in a row, stop instead of spending every round
            # against the same obstacle.
            if results and all(r.is_error for r in results):
                error_streak += 1
            else:
                error_streak = 0
            if error_streak >= 4:
                console.print(
                    "[yellow]Tools failed repeatedly; stopping.[/yellow]"
                )
                status = "stuck"
                last_error = next(
                    (r.content for r in reversed(results) if r.is_error), ""
                )
                final_text = _ERROR_STREAK_GIVE_UP.format(error=last_error[:300])
                console.print(final_text)
                append_assistant_turn(history, final_text)
                maybe_save_session(cfg, history, selection)
                break

            # Retry governor: one tool failing with the same error class too many
            # times (even with varying arguments) is a dead end — stop with a
            # blocker summary instead of burning the round budget.
            worst_class = max(error_class_counts, key=error_class_counts.get, default=None)
            if worst_class and error_class_counts[worst_class] >= ERROR_CLASS_LIMIT:
                console.print(
                    "[yellow]Repeated tool failure of the same kind; stopping.[/yellow]"
                )
                status = "stuck"
                tool_name, _, eclass = worst_class.partition("::")
                final_text = _GOVERNOR_GIVE_UP.format(
                    tool=tool_name,
                    error_class=eclass,
                    error=error_class_last.get(worst_class, "")[:300],
                )
                console.print(final_text)
                append_assistant_turn(history, final_text)
                maybe_save_session(cfg, history, selection)
                break

            edit_followup = process_edit_round(
                calls,
                results,
                cwd=cfg.cwd,
                user_prompt=user_prompt,
                completed_edits=completed_edits,
            )
            if edit_followup:
                history.append({"role": "user", "content": edit_followup})
            web_nudge = web_fetch_failed_nudge(results)
            if web_nudge:
                console.print(
                    "[yellow]web_fetch failed; redirecting the model to web_search.[/yellow]"
                )
                history.append({"role": "user", "content": web_nudge})
            if round_policy_error and not policy_nudge_sent:
                history.append({"role": "user", "content": POLICY_NUDGE_MESSAGE})
                policy_nudge_sent = True
            maybe_save_session(cfg, history, selection)
        else:
            status = "max_rounds"
            final_text = (
                strip_tool_markup(content).strip()
                if content
                else "Reached the round limit without a final answer."
            )
            maybe_save_session(cfg, history, selection)

        if final_text:
            for warning in emit_hook_event(
                cfg,
                "after_final_answer",
                {"answer": final_text, "status": status},
            ):
                console.print(f"[yellow]{warning}[/yellow]")
        console.print(f"[dim]{format_token_usage_line(cfg.token_usage)}[/dim]")
        return final_text
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    finally:
        close_mcp_manager(cfg.cwd)
        if tokens_prompt_peak > 0:
            ctx = selection.context_length
            pct = tokens_prompt_peak / ctx * 100 if ctx else 0.0
            color = "green" if pct < 60 else "yellow" if pct < 85 else "red"
            console.print(
                f"[dim]Tokens: {tokens_prompt_last:,} prompt | "
                f"{tokens_completion_total:,} generated | "
                f"[{color}]{tokens_prompt_peak:,}/{ctx:,} context peak "
                f"({pct:.0f}%)[/{color}][/dim]"
            )
        if run_log:
            run_log.record_token_stats(
                tokens_prompt_last=tokens_prompt_last,
                tokens_prompt_peak=tokens_prompt_peak,
                tokens_completion_total=tokens_completion_total,
            )
            finalize_error = log_error
            if status == "max_rounds" and not finalize_error:
                finalize_error = final_text or "Reached the round limit without a final answer."
            run_log.finalize(
                status=status,
                final_answer=final_text,
                conversation=history,
                error=finalize_error,
            )
