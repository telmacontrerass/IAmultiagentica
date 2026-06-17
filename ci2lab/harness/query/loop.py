"""
Bucle ReAct del arnés agéntico.

Flujo por ronda:
  1. Recortar historial al contexto del modelo
  2. Llamar al LLM (streaming opcional)
  3. Detectar tool calls (native, XML o fenced)
  4. Ejecutar herramientas → añadir resultados
  5. Repetir hasta respuesta sin tools o max_rounds
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

from ci2lab.console import console
from ci2lab.contracts.types import HardwareProfile, ModelSelection
from ci2lab.harness.context import manage_context, trim_messages
from ci2lab.harness.edit_followup import EditSignature, process_edit_round
from ci2lab.harness.llm_client import LLMClient
from ci2lab.harness.llm_errors import LLMError, classify_request_error
from ci2lab.harness.messages import append_assistant_turn, append_tool_results
from ci2lab.harness.mcp.session import close_mcp_manager
from ci2lab.harness.parsing import (
    looks_like_unparsed_tool_attempt,
    resolve_tool_calls,
    strip_tool_markup,
)
from ci2lab.harness.prompts import build_system_prompt
from ci2lab.harness.query.llm_io import call_llm
from ci2lab.harness.query.documents import (
    document_direct_answer,
    document_request_missing_message,
    forced_document_read_tool_call,
)
from ci2lab.harness.query.nudges import (
    forced_pdf_read_tool_call,
    is_pdf_read_tool_call,
    pdf_tool_result_followup,
    pdf_tool_retry_hint,
    summarize_args,
    web_fetch_failed_nudge,
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
from ci2lab.harness.token_usage import format_token_usage_line
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult


def _status(label: str) -> None:
    console.print(f"[dim cyan]{label}[/dim cyan]")


def _initial_progress_label(user_prompt: str) -> str:
    """Describe the first model round in user-friendly terms."""
    text = user_prompt.lower()
    if any(word in text for word in ("pdf", "docx", "document", "documento", "archivo")):
        return "Preparing to read the document..."
    if any(word in text for word in ("web", "internet", "latest", "current", "hoy", "actual")):
        return "Checking what information is needed..."
    if re.search(r"\b(code|codigo|código|test|bug|fix|implement)\b", text):
        return "Planning the code change..."
    return "Deciding the next step..."


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


def _current_request_anchor(user_prompt: str) -> dict[str, str]:
    return {
        "role": "user",
        "content": (
            "La peticion actual del usuario es:\n"
            f"{user_prompt}\n\n"
            "Responde solo a eso usando los resultados de herramientas ya "
            "disponibles. No retomes una tarea anterior ni propongas crear "
            "archivos si el usuario no lo pidio."
        ),
    }


def _role_anchor_message(role_anchor: str) -> dict[str, str]:
    return {
        "role": "user",
        "content": role_anchor,
    }


_EXPLICIT_URL_RE = re.compile(r"https?://\S+")
_DOCX_PATH_RE = re.compile(r"(?P<path>[^\s`\"']+\.docx)\b", re.IGNORECASE)
_LS_DIR_RE = re.compile(r"(?:^|\s)ls\s+(?P<path>[^\s;&|]+)")


def _print_model_step(content: str, *, already_streamed: bool) -> None:
    """Show non-tool text from a model round before executing tools."""
    display = strip_tool_markup(content).strip()
    if not display or already_streamed:
        return
    console.print(f"[dim]Modelo:[/dim] {display}")


def _looks_like_docx_to_pdf_goal(user_prompt: str) -> bool:
    text = user_prompt.lower()
    convert_words = ("convert", "convierte", "convertir", "pasar", "export")
    docx_words = ("docx", "word")
    return (
        any(word in text for word in convert_words)
        and any(word in text for word in docx_words)
        and "pdf" in text
    )


def _output_pdf_for_docx(source: str) -> str:
    return re.sub(r"\.docx$", ".pdf", source, flags=re.IGNORECASE)


def _first_docx_path_from_result(call: ToolCall, result: ToolResult) -> str | None:
    if result.is_error:
        return None
    matches = [match.group("path") for match in _DOCX_PATH_RE.finditer(result.content)]
    if not matches:
        return None
    for match in matches:
        if "/" in match or "\\" in match:
            return match

    dirname: str | None = None
    if call.name in {"ls", "tree", "glob"}:
        dirname = str(call.arguments.get("path") or "").strip()
    elif call.name == "bash":
        command = str(call.arguments.get("command") or "")
        ls_match = _LS_DIR_RE.search(command)
        if ls_match:
            dirname = ls_match.group("path").strip()

    filename = matches[0]
    if dirname and dirname not in {".", "./"}:
        return f"{dirname.rstrip('/')}/{filename}"
    return filename


def _is_repeated_discovery_call(calls: list[ToolCall]) -> bool:
    if len(calls) != 1:
        return False
    call = calls[0]
    if call.name in {"ls", "glob", "grep", "tree"}:
        return True
    if call.name == "bash":
        command = str(call.arguments.get("command") or "").strip().lower()
        return command.startswith(("ls ", "find ", "dir "))
    return False


def _forced_docx_to_pdf_call(
    user_prompt: str,
    calls: list[ToolCall],
    found_docx_path: str | None,
) -> ToolCall | None:
    if (
        not found_docx_path
        or not _looks_like_docx_to_pdf_goal(user_prompt)
        or not _is_repeated_discovery_call(calls)
    ):
        return None
    return ToolCall(
        name="docx_to_pdf",
        arguments={
            "source": found_docx_path,
            "output": _output_pdf_for_docx(found_docx_path),
        },
        call_id=f"auto_docx_to_pdf_{uuid.uuid4().hex[:8]}",
    )


_NO_INTERNET_RE = re.compile(
    r"(no tengo acceso a internet|"
    r"no puedo buscar en tiempo real|"
    r"no tengo capacidad de acceder a la web)",
    re.IGNORECASE,
)
_STOP_TOOLS_RE = re.compile(
    r"(responde con lo que sabes|"
    r"deja de repetir|"
    r"contesta con lo que tengas|"
    r"no sigas buscando)",
    re.IGNORECASE,
)
_FACTUAL_TOPIC_RE = re.compile(
    r"\b(resultado|marcador|score|partido|vs\b|bitcoin|btc|precio|latest|actual|"
    r"noticia|version|versi[oó]n|cotizaci[oó]n)\b",
    re.IGNORECASE,
)
_WEB_SIGNAL_RE = re.compile(
    r"\b(web|internet|online|tiempo real|live|hoy|now|actual|latest|precio|bitcoin|btc)\b",
    re.IGNORECASE,
)
_EXPLICIT_LOCAL_RE = re.compile(
    r"\b(repo|repositorio|archivo|archivos|file|files|carpeta|directorio|"
    r"path|ruta|read_file|tree|ls|glob|grep)\b",
    re.IGNORECASE,
)
_MCP_PLACEHOLDER_RE = re.compile(
    r"(mcp_server_name|placeholder|example|your[_-]?server)",
    re.IGNORECASE,
)
_FACTUAL_FILESYSTEM_TOOLS = {"ls", "tree", "glob", "grep", "read_file", "read_document"}
_BTC_PRICE_QUERY_RE = re.compile(r"\b(bitcoin|btc)\b.*\b(precio|price|cotizaci[oó]n)\b|\b(precio|price|cotizaci[oó]n)\b.*\b(bitcoin|btc)\b", re.IGNORECASE)
_BTC_SUPPLY_DRIFT_RE = re.compile(r"\b(circulaci[oó]n|suministro|miner[ií]a|en circulaci[oó]n)\b", re.IGNORECASE)
_PRICE_LIKE_ANSWER_RE = re.compile(r"(\$|usd|eur|d[oó]lar|precio|price|cotizaci[oó]n)", re.IGNORECASE)


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
            "[yellow]web_fetch redirigido a web_search "
            "(el modelo invento una URL; buscando primero).[/yellow]"
        )
    return redirected


def _history_requests_stop_tools(history: list[dict[str, Any]]) -> bool:
    return any(
        m.get("role") == "user" and _STOP_TOOLS_RE.search(str(m.get("content", "")))
        for m in history
    )


def _is_factual_web_task(user_prompt: str) -> bool:
    prompt = user_prompt.strip()
    if prompt.startswith("/live_fact_lookup"):
        return True
    return (
        bool(_FACTUAL_TOPIC_RE.search(prompt))
        and bool(_WEB_SIGNAL_RE.search(prompt))
        and not bool(_EXPLICIT_LOCAL_RE.search(prompt))
    )


def _normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def _is_filesystem_bash(call: ToolCall) -> bool:
    if call.name != "bash":
        return False
    command = str(call.arguments.get("command") or "").strip().lower()
    return command.startswith(("ls", "dir", "tree", "cat ", "type "))


def _contains_web_tool_call(calls: list[ToolCall]) -> bool:
    return any(call.name in {"web_search", "web_fetch"} for call in calls)


def _web_focus_followup(user_prompt: str) -> str:
    return (
        "Pregunta original del usuario:\n"
        f"{user_prompt}\n\n"
        "Responde SOLO a esa pregunta. No cambies la pregunta a otro dato "
        "relacionado encontrado en la fuente (por ejemplo, suministro, historia "
        "o minería). Si no puedes extraer claramente el dato pedido, dilo con "
        "una advertencia y explica que te basas solo en snippets o datos "
        "parciales."
    )


def _looks_like_bitcoin_price_drift(user_prompt: str, final_text: str) -> bool:
    if not _BTC_PRICE_QUERY_RE.search(user_prompt):
        return False
    if not _BTC_SUPPLY_DRIFT_RE.search(final_text):
        return False
    return not bool(_PRICE_LIKE_ANSWER_RE.search(final_text))


def _filter_factual_web_calls(
    calls: list[ToolCall],
    *,
    factual_web_task: bool,
    seen_web_queries: set[str],
) -> tuple[list[ToolCall], bool]:
    if not factual_web_task:
        return calls, False

    filtered: list[ToolCall] = []
    seen_this_batch: set[str] = set()
    blocked_any = False
    for call in calls:
        if call.name in _FACTUAL_FILESYSTEM_TOOLS or _is_filesystem_bash(call):
            blocked_any = True
            continue
        if call.name == "mcp_call":
            server = str(call.arguments.get("server", ""))
            if not server or _MCP_PLACEHOLDER_RE.search(server):
                blocked_any = True
                continue
        if call.name == "web_search":
            query = _normalize_query(str(call.arguments.get("query", "")))
            if query and (query in seen_web_queries or query in seen_this_batch):
                blocked_any = True
                continue
            if query:
                seen_this_batch.add(query)
        filtered.append(call)
    return filtered, blocked_any


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
            f"Sesión {cfg.session_id} eliminada."
            if deleted
            else "No había sesión guardada que eliminar."
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

    recent_sigs: deque[str] = deque(maxlen=6)
    policy_blocked_sigs: set[str] = set()
    policy_nudge_sent = False
    stuck_rounds = 0
    stuck_nudges = 0
    error_streak = 0
    unparsed_tool_nudges = 0
    summary_failures = 0
    pdf_tool_nudges = 0
    pdf_tool_used = False
    web_search_used = False  # becomes True once web_search runs in this turn
    web_fetch_http_error_seen = False
    web_focus_nudges = 0
    price_drift_nudges = 0
    seen_web_queries: set[str] = set()
    found_docx_path: str | None = None
    web_capability_nudge_sent = False
    stop_tools_nudge_sent = False
    completed_edits: set[EditSignature] = set()
    final_text = ""
    content = ""
    status = "success"
    log_error: str | None = None
    rounds_completed = 0
    hit_max_rounds = False
    # Contadores de tokens reales (rellenados por Ollama tras cada llamada LLM).
    tokens_prompt_last: int = 0       # prompt_tokens de la última ronda
    tokens_prompt_peak: int = 0       # máximo de prompt_tokens visto en cualquier ronda
    tokens_completion_total: int = 0  # completion_tokens acumulados (generación real)

    run_log = RunLogger.maybe_create(cfg, selection, user_prompt)
    if run_log:
        run_log.start()

    try:
        for round_num in range(1, cfg.max_rounds + 1):
            console.print(f"[dim]── Ronda {round_num} ──[/dim]")
            rounds_completed = round_num
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
            factual_web_task = _is_factual_web_task(user_prompt)
            initial_document_call = (
                forced_document_read_tool_call(user_prompt, cfg.cwd)
                if round_num == 1
                else None
            )
            if initial_document_call:
                calls = [initial_document_call]
                _status(_tool_progress_label(calls))
            else:
                missing_document_message = (
                    document_request_missing_message(user_prompt, cfg.cwd)
                    if round_num == 1
                    else None
                )
                if missing_document_message:
                    final_text = missing_document_message
                    console.print(final_text)
                    append_assistant_turn(history, final_text)
                    maybe_save_session(cfg, history, selection)
                    break

                trimmed = trim_messages(history, selection.context_length)
                stop_tools_requested = _history_requests_stop_tools(history)
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
                _status(_initial_progress_label(user_prompt))
                streamed_this_round = stream_this_round
                try:
                    llm_response = call_llm(
                        client,
                        trimmed,
                        tools=tools,
                        stream=stream_this_round,
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
                usage = llm_response.usage
                cfg.token_usage.record_call(usage)
                if usage and usage.available:
                    tokens_prompt_last = usage.prompt_tokens
                    tokens_completion_total += usage.completion_tokens
                    if usage.prompt_tokens > tokens_prompt_peak:
                        tokens_prompt_peak = usage.prompt_tokens
                if run_log:
                    run_log.record_token_usage(
                        round_num=round_num,
                        usage=usage,
                    )
                if on_round:
                    on_round(round_num, content)
                calls = resolve_tool_calls(
                    content,
                    llm_response.tool_calls,
                    tool_mode=selection.tool_mode,
                )
                if _history_requests_stop_tools(history):
                    calls = []
                calls = _prepend_missing_reads(calls, user_prompt)
                calls = _redirect_fetch_to_search(
                    calls, user_prompt, web_search_used
                )
                calls, blocked_web_calls = _filter_factual_web_calls(
                    calls,
                    factual_web_task=factual_web_task,
                    seen_web_queries=seen_web_queries,
                )
                if blocked_web_calls:
                    append_assistant_turn(history, content)
                    history.append({
                        "role": "user",
                        "content": (
                            "No repitas la misma búsqueda. Usa los resultados ya "
                            "disponibles o intenta leer una fuente si procede. Si no "
                            "puedes verificar más, responde con advertencia."
                        ),
                    })
                    maybe_save_session(cfg, history, selection)
                    continue
                if calls:
                    if not (factual_web_task and _contains_web_tool_call(calls)):
                        _print_model_step(content, already_streamed=streamed_this_round)
                    # No conservar texto libre del modelo antes del resultado real de tools.
                    content = ""
            forced_pdf_call = (
                forced_pdf_read_tool_call(user_prompt)
                if not calls and not pdf_tool_used and pdf_tool_nudges >= 1
                else None
            )
            if forced_pdf_call:
                _status(_tool_progress_label([forced_pdf_call]))
                console.print(
                    "[yellow]El modelo siguió sin usar herramientas; ejecutando "
                    "read_file automáticamente para el PDF mencionado.[/yellow]"
                )
                calls = [forced_pdf_call]

            if not calls:
                if (
                    _history_requests_stop_tools(history)
                    and not (strip_tool_markup(content).strip() or content.strip())
                    and not stop_tools_nudge_sent
                ):
                    stop_tools_nudge_sent = True
                    append_assistant_turn(history, content)
                    history.append({
                        "role": "user",
                        "content": (
                            "No uses herramientas. Responde ahora con lo disponible y "
                            "añade una advertencia breve si faltan fuentes completas."
                        ),
                    })
                    maybe_save_session(cfg, history, selection)
                    continue
                pdf_hint = pdf_tool_retry_hint(
                    user_prompt,
                    selection_tool_mode=selection.tool_mode,
                )
                if (
                    pdf_hint
                    and not pdf_tool_used
                    and pdf_tool_nudges < 1
                    and selection.supports_tools
                ):
                    pdf_tool_nudges += 1
                    console.print(
                        "[yellow]La petición menciona un PDF pero el modelo no usó "
                        "herramientas; reintentando con read_file/grep.[/yellow]"
                    )
                    append_assistant_turn(history, content)
                    history.append({"role": "user", "content": pdf_hint})
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
                    if selection.tool_mode == "fenced":
                        hint = (
                            "Your previous tool call was not executed. "
                            "Use a fenced block with the tool name as the tag, e.g.\n"
                            "```write_file\n"
                            '{"path": "file.py", "content": "..."}\n'
                            "```\n"
                            "Do not put write_file inside a bash block. "
                            "Do not reply with plain JSON only."
                        )
                    else:
                        hint = (
                            "Your previous tool call was not executed. "
                            "Invoke the tool through function calling, or use a "
                            "```write_file fenced block with JSON arguments."
                        )
                    history.append({"role": "user", "content": hint})
                    maybe_save_session(cfg, history, selection)
                    continue

                final_text = strip_tool_markup(content).strip() or content.strip()
                if (
                    final_text
                    and factual_web_task
                    and price_drift_nudges < 1
                    and _looks_like_bitcoin_price_drift(user_prompt, final_text)
                ):
                    price_drift_nudges += 1
                    append_assistant_turn(history, final_text or content)
                    history.append({
                        "role": "user",
                        "content": _web_focus_followup(user_prompt),
                    })
                    maybe_save_session(cfg, history, selection)
                    continue
                if (
                    final_text
                    and not calls
                    and web_search_available
                    and not web_capability_nudge_sent
                    and _NO_INTERNET_RE.search(final_text)
                ):
                    web_capability_nudge_sent = True
                    append_assistant_turn(history, final_text or content)
                    history.append({
                        "role": "user",
                        "content": (
                            "You can use `web_search` for live info without a URL, "
                            "then `web_fetch` for selected sources."
                        ),
                    })
                    maybe_save_session(cfg, history, selection)
                    continue
                _status("Finalizing the answer...")
                if final_text and streamed_this_round:
                    console.print()
                elif final_text:
                    console.print(final_text)
                append_assistant_turn(history, final_text or content)
                maybe_save_session(cfg, history, selection)
                break

            forced_conversion_call = _forced_docx_to_pdf_call(
                user_prompt,
                calls,
                found_docx_path,
            )
            if forced_conversion_call:
                console.print(
                    "[yellow]Ya se encontró un .docx; avanzando a docx_to_pdf "
                    "en vez de repetir la búsqueda.[/yellow]"
                )
                calls = [forced_conversion_call]
                stuck_rounds = 0

            sig = "|".join(
                f"{c.name}:{hashlib.md5(str(c.arguments).encode()).hexdigest()[:8]}"
                for c in calls
            )
            if any(is_pdf_read_tool_call(c.name, c.arguments) for c in calls):
                pdf_tool_used = True
            if any(c.name == "web_search" for c in calls):
                web_search_used = True
                for call in calls:
                    if call.name == "web_search":
                        query = _normalize_query(str(call.arguments.get("query", "")))
                        if query:
                            seen_web_queries.add(query)
            if sig in recent_sigs:
                stuck_rounds += 1
            else:
                stuck_rounds = 0
            recent_sigs.append(sig)

            if stuck_rounds >= 2:
                stuck_nudges += 1
                if stuck_nudges > 2:
                    console.print(
                        "[yellow]Bucle persistente; deteniendo y respondiendo "
                        "con lo disponible.[/yellow]")
                    status = "stuck"
                    final_text = (
                        strip_tool_markup(content).strip()
                        or "No pude completar la tarea: se repitió la misma "
                        "herramienta sin avanzar. Revisa el último error mostrado "
                        "arriba (permisos del skill, archivo o formato)."
                    )
                    console.print(final_text)
                    append_assistant_turn(history, final_text)
                    maybe_save_session(cfg, history, selection)
                    break
                console.print("[yellow]Bucle detectado; pidiendo respuesta final.[/yellow]")
                history.append({
                    "role": "user",
                    "content": (
                        "Deja de repetir la misma herramienta o los mismos "
                        "argumentos. Si una herramienta está bloqueada por el "
                        "skill, usa la herramienta permitida equivalente "
                        "(`ls`, `grep`, `glob`, `read_file`). No respondas a esta "
                        "instrucción ni expliques que vas a cambiar de estrategia. "
                        "Responde ahora a la petición original del usuario usando "
                        "los resultados de herramientas ya disponibles.\n\n"
                        f"Petición original: {user_prompt}"
                    ),
                })
                continue

            append_assistant_turn(history, content, calls)
            results = []
            round_policy_error = False
            _status(_tool_progress_label(calls))
            for call in calls:
                console.print(f"[cyan]▶ {call.name}[/cyan] {summarize_args(call.arguments)}")
                started_at = datetime.now(timezone.utc)
                sig = tool_call_signature(call)
                if sig in policy_blocked_sigs:
                    result = ToolResult(
                        tool_name=call.name,
                        content=POLICY_REPEAT_MESSAGE,
                        is_error=True,
                        call_id=call.call_id,
                        outcome="blocked_by_policy",
                    )
                else:
                    result = execute_tool(call, cfg)
                    if is_policy_error(result):
                        policy_blocked_sigs.add(sig)
                        round_policy_error = True
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
            if cfg.role_anchor:
                history.append(_role_anchor_message(cfg.role_anchor))
            history.append(_current_request_anchor(user_prompt))
            for call, result in zip(calls, results, strict=False):
                docx_path = _first_docx_path_from_result(call, result)
                if docx_path:
                    found_docx_path = docx_path

            # Corte por racha de errores: aunque los argumentos cambien cada
            # ronda (y el detector de firmas no lo vea como bucle), si todas las
            # herramientas fallan varias rondas seguidas, paramos en vez de
            # gastar todas las rondas contra el mismo obstáculo.
            if results and all(r.is_error for r in results):
                error_streak += 1
            else:
                error_streak = 0
            if error_streak >= 4:
                console.print(
                    "[yellow]Las herramientas fallaron repetidamente; "
                    "deteniendo.[/yellow]")
                status = "stuck"
                last_error = next(
                    (r.content for r in reversed(results) if r.is_error), ""
                )
                final_text = (
                    "No pude completar la tarea: las herramientas fallaron "
                    "repetidamente. Último error: "
                    f"{last_error[:300]}"
                )
                console.print(final_text)
                append_assistant_turn(history, final_text)
                maybe_save_session(cfg, history, selection)
                break

            direct_answer = document_direct_answer(results, user_prompt)
            if direct_answer:
                final_text = direct_answer
                _status("Finalizing the answer...")
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
            pdf_followup = pdf_tool_result_followup(results, user_prompt)
            if pdf_followup:
                history.append({"role": "user", "content": pdf_followup})
            web_nudge = web_fetch_failed_nudge(results)
            if web_nudge:
                web_fetch_http_error_seen = True
                console.print(
                    "[yellow]web_fetch falló; redirigiendo al modelo hacia web_search.[/yellow]"
                )
                history.append({"role": "user", "content": web_nudge})
            elif (
                factual_web_task
                and _contains_web_tool_call(calls)
                and web_focus_nudges < 2
            ):
                web_focus_nudges += 1
                history.append({
                    "role": "user",
                    "content": _web_focus_followup(user_prompt),
                })
            if round_policy_error and not policy_nudge_sent:
                history.append({"role": "user", "content": POLICY_NUDGE_MESSAGE})
                policy_nudge_sent = True
            maybe_save_session(cfg, history, selection)
        else:
            hit_max_rounds = True
            status = "max_rounds"
            final_text = (
                strip_tool_markup(content).strip()
                if content
                else "Se alcanzó el límite de rondas sin respuesta final."
            )
            maybe_save_session(cfg, history, selection)

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
                f"{tokens_completion_total:,} generados | "
                f"[{color}]{tokens_prompt_peak:,}/{ctx:,} pico contexto "
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
                finalize_error = final_text or "Se alcanzó el límite de rondas sin respuesta final."
            run_log.finalize(
                status=status,
                final_answer=final_text,
                conversation=history,
                error=finalize_error,
            )
