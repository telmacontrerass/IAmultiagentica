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
)
from ci2lab.harness.query.session_hooks import maybe_save_session
from ci2lab.harness.run_logger import RunLogger
from ci2lab.harness.session import delete_session, is_delete_session_request
from ci2lab.harness.security.policy import (
    POLICY_NUDGE_MESSAGE,
    POLICY_REPEAT_MESSAGE,
    is_policy_error,
    tool_call_signature,
)
from ci2lab.harness.tools.registry import execute_tool, get_function_schemas
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult


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
    unparsed_tool_nudges = 0
    summary_failures = 0
    pdf_tool_nudges = 0
    pdf_tool_used = False
    completed_edits: set[EditSignature] = set()
    final_text = ""
    content = ""
    status = "success"
    log_error: str | None = None
    rounds_completed = 0
    hit_max_rounds = False

    run_log = RunLogger.maybe_create(cfg, selection, user_prompt)
    if run_log:
        run_log.start()

    try:
        for round_num in range(1, cfg.max_rounds + 1):
            console.print(f"[dim]── Ronda {round_num} ──[/dim]")
            rounds_completed = round_num
            if run_log:
                run_log.set_rounds_completed(round_num)

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
            initial_document_call = (
                forced_document_read_tool_call(user_prompt, cfg.cwd)
                if round_num == 1
                else None
            )
            if initial_document_call:
                console.print(
                    "[yellow]Petición documental detectada; leyendo el documento "
                    "con read_document.[/yellow]"
                )
                calls = [initial_document_call]
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
                tools = get_function_schemas(cfg) if selection.supports_tools else None
                # Evita mostrar texto tentativo en rondas con herramientas;
                # solo mostramos contenido final cuando no hay tool calls.
                stream_this_round = cfg.stream and not selection.supports_tools
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
                if on_round:
                    on_round(round_num, content)
                calls = resolve_tool_calls(
                    content,
                    llm_response.tool_calls,
                    tool_mode=selection.tool_mode,
                )
                calls = _prepend_missing_reads(calls, user_prompt)
                if calls:
                    # No conservar texto libre del modelo antes del resultado real de tools.
                    content = ""
            forced_pdf_call = (
                forced_pdf_read_tool_call(user_prompt)
                if not calls and not pdf_tool_used and pdf_tool_nudges >= 1
                else None
            )
            if forced_pdf_call:
                console.print(
                    "[yellow]El modelo siguió sin usar herramientas; ejecutando "
                    "read_file automáticamente para el PDF mencionado.[/yellow]"
                )
                calls = [forced_pdf_call]

            if not calls:
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
                if final_text and not cfg.stream:
                    console.print(final_text)
                elif final_text and cfg.stream:
                    console.print()
                append_assistant_turn(history, final_text or content)
                maybe_save_session(cfg, history, selection)
                break

            sig = "|".join(
                f"{c.name}:{hashlib.md5(str(c.arguments).encode()).hexdigest()[:8]}"
                for c in calls
            )
            if any(is_pdf_read_tool_call(c.name, c.arguments) for c in calls):
                pdf_tool_used = True
            if sig in recent_sigs:
                stuck_rounds += 1
            else:
                stuck_rounds = 0
            recent_sigs.append(sig)

            if stuck_rounds >= 2:
                console.print("[yellow]Bucle detectado; pidiendo respuesta final.[/yellow]")
                history.append({
                    "role": "user",
                    "content": (
                        "Deja de repetir la misma herramienta. "
                        "Responde al usuario con lo que ya sabes."
                    ),
                })
                continue

            append_assistant_turn(history, content, calls)
            results = []
            round_policy_error = False
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
            direct_answer = document_direct_answer(results, user_prompt)
            if direct_answer:
                final_text = direct_answer
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

        return final_text
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    finally:
        close_mcp_manager(cfg.cwd)
        if run_log:
            finalize_error = log_error
            if status == "max_rounds" and not finalize_error:
                finalize_error = final_text or "Se alcanzó el límite de rondas sin respuesta final."
            run_log.finalize(
                status=status,
                final_answer=final_text,
                conversation=history,
                error=finalize_error,
            )
