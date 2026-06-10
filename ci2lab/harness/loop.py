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
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

from rich.console import Console
from rich.live import Live
from rich.text import Text

from ci2lab.contracts.types import HardwareProfile, ModelSelection
from ci2lab.harness.context import trim_messages
from ci2lab.harness.llm_client import LLMClient, LLMResponse, StreamToken
from ci2lab.harness.llm_errors import LLMError, classify_request_error
from ci2lab.harness.messages import append_assistant_turn, append_tool_results
from ci2lab.harness.parsing import resolve_tool_calls, strip_tool_markup
from ci2lab.harness.prompts import build_system_prompt
from ci2lab.harness.run_logger import RunLogger
from ci2lab.harness.session import save_session
from ci2lab.harness.policy import (
    POLICY_NUDGE_MESSAGE,
    POLICY_REPEAT_MESSAGE,
    is_policy_error,
    tool_call_signature,
)
from ci2lab.harness.tools.registry import FUNCTION_SCHEMAS, execute_tool
from ci2lab.harness.types import AgentConfig, ToolResult

console = Console()


def run_agent(
    user_prompt: str,
    selection: ModelSelection,
    *,
    hardware: HardwareProfile | None = None,  # noqa: ARG001
    config: AgentConfig | None = None,
    messages: list[dict[str, Any]] | None = None,
    on_round: Callable[[int, str], None] | None = None,
) -> str:
    """
    Ejecuta el bucle agéntico y devuelve la respuesta final.

    Si `messages` se pasa (sesión reanudada), se continúa el historial y se
    añade `user_prompt` como nuevo mensaje de usuario.
    """
    cfg = config or AgentConfig(cwd=".")
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

    tools = FUNCTION_SCHEMAS if selection.supports_tools else None
    recent_sigs: deque[str] = deque(maxlen=6)
    policy_blocked_sigs: set[str] = set()
    policy_nudge_sent = False
    stuck_rounds = 0
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

            trimmed = trim_messages(history, selection.context_length)

            try:
                llm_response = _call_llm(client, trimmed, tools=tools, stream=cfg.stream)
            except LLMError as exc:
                status = "llm_error"
                log_error = exc.user_message
                _maybe_save(cfg, history, selection)
                raise
            except Exception as exc:  # noqa: BLE001
                err = classify_request_error(
                    exc, model=selection.ollama_tag, url=client.chat_url
                )
                console.print(f"[red]{err.user_message}[/red]")
                status = "llm_error"
                log_error = err.user_message
                _maybe_save(cfg, history, selection)
                raise err from exc

            content = llm_response.content or ""
            if on_round:
                on_round(round_num, content)

            calls = resolve_tool_calls(
                content,
                llm_response.tool_calls,
                tool_mode=selection.tool_mode,
            )

            if not calls:
                final_text = strip_tool_markup(content).strip() or content.strip()
                if final_text and not cfg.stream:
                    console.print(final_text)
                elif final_text and cfg.stream:
                    console.print()  # newline tras streaming
                append_assistant_turn(history, final_text or content)
                _maybe_save(cfg, history, selection)
                break

            sig = "|".join(
                f"{c.name}:{hashlib.md5(str(c.arguments).encode()).hexdigest()[:8]}"
                for c in calls
            )
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
                console.print(f"[cyan]▶ {call.name}[/cyan] {_summarize_args(call.arguments)}")
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
            if round_policy_error and not policy_nudge_sent:
                history.append({"role": "user", "content": POLICY_NUDGE_MESSAGE})
                policy_nudge_sent = True
            _maybe_save(cfg, history, selection)
        else:
            hit_max_rounds = True
            status = "max_rounds"
            final_text = (
                strip_tool_markup(content).strip()
                if content
                else "Se alcanzó el límite de rondas sin respuesta final."
            )
            _maybe_save(cfg, history, selection)

        return final_text
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    finally:
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


def _call_llm(
    client: LLMClient,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    stream: bool,
) -> LLMResponse:
    if not stream:
        return client.chat(messages, tools=tools)

    llm_response: LLMResponse | None = None
    buffer = Text()

    with Live(buffer, console=console, refresh_per_second=12, transient=False) as live:
        for event in client.stream_chat(messages, tools=tools):
            if isinstance(event, StreamToken):
                buffer.append(event.text)
                live.update(buffer)
            else:
                llm_response = event

    if llm_response is None:
        return LLMResponse(content=buffer.plain, tool_calls=[], raw={})
    if not llm_response.content and buffer.plain:
        llm_response = LLMResponse(
            content=buffer.plain,
            tool_calls=llm_response.tool_calls,
            raw=llm_response.raw,
        )
    return llm_response


def _maybe_save(
    cfg: AgentConfig,
    messages: list[dict[str, Any]],
    selection: ModelSelection,
) -> None:
    if not cfg.session_id:
        return
    path = save_session(
        cfg.session_id,
        messages=messages,
        model_tag=selection.ollama_tag,
        cwd=cfg.cwd,
    )
    console.print(f"[dim]Sesión guardada: {path}[/dim]")


def _summarize_args(args: dict) -> str:
    if "command" in args:
        cmd = args["command"]
        return cmd[:60] + ("..." if len(cmd) > 60 else "")
    if "path" in args:
        return str(args["path"])
    if "pattern" in args:
        return str(args["pattern"])
    return ""
