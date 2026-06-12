"""
Compactación de contexto inspirada en Claude Code (micro-compact + auto-compact).

Capas, de barata a cara:
  1. micro_compact()      — sustituye resultados antiguos de tools por un stub
  2. summarize_history()  — una llamada LLM que resume turnos antiguos
  3. trim_messages()      — recorte mecánico (fallback existente en context.py)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ci2lab.harness.context import estimate_tokens

TOOL_RESULT_STUB = "[Old tool result cleared to save context — re-run the tool if needed]"
SUMMARY_PREFIX = "[Summary of earlier conversation]"

# Tools cuyos resultados antiguos se pueden regenerar fácilmente (idea de
# COMPACTABLE_TOOLS en claude-code microCompact.ts).
COMPACTABLE_TOOLS = frozenset({
    "read_file",
    "bash",
    "grep",
    "glob",
    "ls",
    "web_fetch",
    "git_status",
    "git_diff",
    "write_file",
    "edit_file",
})

# Resultados de tool más cortos que esto no merecen stub (el stub no ahorra nada).
MIN_STUB_CHARS = 200
# Cuántos resultados de tool recientes se conservan intactos.
KEEP_RECENT_TOOL_RESULTS = 4
# Cuántos mensajes recientes (no system) sobreviven la compactación por resumen.
KEEP_RECENT_MESSAGES = 6
# Umbral de disparo: fracción de la ventana efectiva (contexto - reserva salida).
COMPACT_THRESHOLD_PCT = 0.8
# Cortacircuitos: tras N fallos seguidos de resumen, dejar de intentarlo.
MAX_SUMMARY_FAILURES = 3

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def conservative_estimate(messages: list[dict[str, Any]]) -> int:
    """Estimación de tokens con margen 4/3 (como claude-code)."""
    return math.ceil(estimate_tokens(messages) * 4 / 3)


def should_compact(
    messages: list[dict[str, Any]],
    context_length: int,
    *,
    reserve_output: int = 1024,
    threshold_pct: float = COMPACT_THRESHOLD_PCT,
) -> bool:
    threshold = max(512, int((context_length - reserve_output) * threshold_pct))
    return conservative_estimate(messages) > threshold


def _tool_names_by_call_id(messages: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for msg in messages:
        for tc in msg.get("tool_calls") or []:
            call_id = tc.get("id")
            name = (tc.get("function") or {}).get("name")
            if call_id and name:
                names[call_id] = name
    return names


def micro_compact(
    messages: list[dict[str, Any]],
    *,
    keep_recent: int = KEEP_RECENT_TOOL_RESULTS,
) -> tuple[list[dict[str, Any]], int]:
    """
    Sustituye resultados antiguos de tools por un stub corto.

    Conserva intactos los `keep_recent` resultados más recientes y nunca toca
    mensajes de usuario, asistente o system. Devuelve (mensajes, n_stubbed).
    """
    tool_indexes = [
        i for i, m in enumerate(messages)
        if m.get("role") == "tool" and isinstance(m.get("content"), str)
    ]
    candidates = tool_indexes[:-keep_recent] if keep_recent > 0 else tool_indexes
    if not candidates:
        return messages, 0

    names = _tool_names_by_call_id(messages)
    result = list(messages)
    stubbed = 0
    for i in candidates:
        msg = result[i]
        content = msg.get("content") or ""
        if len(content) <= MIN_STUB_CHARS or content == TOOL_RESULT_STUB:
            continue
        tool_name = names.get(str(msg.get("tool_call_id")), "")
        if tool_name and tool_name not in COMPACTABLE_TOOLS:
            continue
        result[i] = {**msg, "content": TOOL_RESULT_STUB}
        stubbed += 1
    return result, stubbed


def _render_transcript(messages: list[dict[str, Any]], max_chars: int) -> str:
    """Convierte mensajes en un transcript plano para el prompt de resumen."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")
        if role == "tool":
            text = (content or "")[:500]
            lines.append(f"TOOL RESULT: {text}")
            continue
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                args = fn.get("arguments", "")
                if isinstance(args, dict):
                    args = json.dumps(args, ensure_ascii=False)
                lines.append(f"ASSISTANT CALLS TOOL: {fn.get('name', '?')}({str(args)[:300]})")
        if isinstance(content, str) and content.strip():
            lines.append(f"{role.upper()}: {content.strip()}")
    transcript = "\n".join(lines)
    if len(transcript) > max_chars:
        transcript = "(transcript truncated; oldest part omitted)\n" + transcript[-max_chars:]
    return transcript


def _split_for_summary(
    messages: list[dict[str, Any]],
    *,
    keep_recent_messages: int = KEEP_RECENT_MESSAGES,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Devuelve (system_msgs, old_msgs_a_resumir, tail_intacto)."""
    system_msgs = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]

    start = max(0, len(rest) - keep_recent_messages)
    # No partir un par assistant(tool_calls) + tool: si el tail empieza en un
    # mensaje tool, extender hacia atrás hasta incluir a su assistant.
    while start > 0 and rest[start].get("role") == "tool":
        start -= 1
    return system_msgs, rest[:start], rest[start:]


def summarize_history(
    client: Any,
    messages: list[dict[str, Any]],
    context_length: int,
    *,
    keep_recent_messages: int = KEEP_RECENT_MESSAGES,
) -> list[dict[str, Any]] | None:
    """
    Resume los turnos antiguos en un único mensaje y conserva el tail reciente.

    Devuelve el historial nuevo, o None si no hay nada que resumir o el modelo
    falla (el caller hace fallback a trim_messages).
    """
    system_msgs, old, tail = _split_for_summary(
        messages, keep_recent_messages=keep_recent_messages
    )
    if not old:
        return None

    prompt = (_PROMPTS_DIR / "compact.md").read_text(encoding="utf-8").strip()
    max_chars = max(4_000, context_length * 2)
    transcript = _render_transcript(old, max_chars)

    try:
        response = client.chat(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "Summarize this conversation transcript:\n\n"
                        f"{transcript}\n\n"
                        "Reply with the summary only, plain text."
                    ),
                },
            ],
            tools=None,
        )
    except Exception:  # noqa: BLE001 — cualquier fallo => fallback a trim
        return None

    summary = (getattr(response, "content", "") or "").strip()
    if not summary or getattr(response, "tool_calls", None):
        return None

    summary_msg = {
        "role": "user",
        "content": f"{SUMMARY_PREFIX}\n\n{summary}",
    }
    return [*system_msgs, summary_msg, *tail]


def manage_context(
    history: list[dict[str, Any]],
    client: Any,
    context_length: int,
    *,
    summary_failures: int = 0,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """
    Aplica las capas de compactación en orden de coste.

    Devuelve (historial, summary_failures, eventos_para_log). Los eventos son
    strings cortos que el loop puede imprimir en gris.
    """
    events: list[str] = []

    if not should_compact(history, context_length):
        return history, summary_failures, events

    history, stubbed = micro_compact(history)
    if stubbed:
        events.append(f"Contexto: micro-compact limpió {stubbed} resultado(s) de tool antiguos.")

    if not should_compact(history, context_length):
        return history, summary_failures, events

    if summary_failures >= MAX_SUMMARY_FAILURES:
        return history, summary_failures, events

    summarized = summarize_history(client, history, context_length)
    if summarized is None:
        summary_failures += 1
        events.append(
            "Contexto: el resumen automático falló; se usará recorte mecánico."
        )
        return history, summary_failures, events

    before = conservative_estimate(history)
    after = conservative_estimate(summarized)
    events.append(
        f"Contexto: historial resumido (~{before} → ~{after} tokens estimados)."
    )
    return summarized, 0, events
