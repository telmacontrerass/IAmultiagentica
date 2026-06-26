"""
Context compaction inspired by Claude Code (micro-compact + auto-compact).

Layers, from cheap to expensive:
  1. micro_compact()      — replaces old tool results with a stub
  2. summarize_history()  — a single LLM call that summarizes old turns
  3. trim_messages()      — mechanical trimming (fallback in trim.py)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ci2lab.harness.context.trim import estimate_tokens

TOOL_RESULT_STUB = "[Old tool result cleared to save context — re-run the tool if needed]"
SUMMARY_PREFIX = "[Summary of earlier conversation]"

# Compact by default: any tool result old enough is replaced by a stub. Only a
# small set of tools is protected, because their output is short, structural, or
# the model is expected to act on it directly (a re-read would lose the plan).
# Inverting the rule this way means new/rare tools (read_document, web_search,
# tree, inspect_file, mcp__*, …) are covered automatically instead of leaking.
NON_COMPACTABLE_TOOLS = frozenset(
    {
        "todo_write",
        "todo_read",
        "ask_user",
    }
)

MIN_STUB_CHARS = 200
KEEP_RECENT_TOOL_RESULTS = 3
KEEP_RECENT_MESSAGES = 6
# Two-stage gate: the cheap, near-lossless micro-compact fires early so context
# stays lean throughout a long task; the expensive LLM summary stays
# conservative so we don't burn a model call (or, with a small context model,
# fire one almost immediately) until trimming is genuinely needed.
MICRO_COMPACT_THRESHOLD_PCT = 0.65
SUMMARY_COMPACT_THRESHOLD_PCT = 0.8
# Back-compat default for should_compact callers that don't specify a stage.
COMPACT_THRESHOLD_PCT = MICRO_COMPACT_THRESHOLD_PCT
MAX_SUMMARY_FAILURES = 3

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def conservative_estimate(messages: list[dict[str, Any]]) -> int:
    """Return a deliberately high token estimate (4/3 of the base) to fire compaction early."""
    return math.ceil(estimate_tokens(messages) * 4 / 3)


def should_compact(
    messages: list[dict[str, Any]],
    context_length: int,
    *,
    reserve_output: int = 1024,
    threshold_pct: float = COMPACT_THRESHOLD_PCT,
) -> bool:
    """Return ``True`` when the conservative token estimate exceeds the compaction threshold.

    Args:
        messages: The conversation history to measure.
        context_length: The model's context window in tokens.
        reserve_output: Tokens held back for the model's output.
        threshold_pct: Fraction of the usable window that triggers compaction.

    Returns:
        ``True`` if compaction should run for this history.
    """
    threshold = max(512, int((context_length - reserve_output) * threshold_pct))
    return conservative_estimate(messages) > threshold


def _tool_names_by_call_id(messages: list[dict[str, Any]]) -> dict[str, str]:
    """Map each assistant tool-call id to the tool name it invoked."""
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
    """Replace old, large tool results with a stub, keeping the most recent ones.

    Args:
        messages: The conversation history.
        keep_recent: Number of most-recent tool results to leave untouched.

    Returns:
        A ``(messages, stubbed)`` pair: the (possibly new) history and the count
        of tool results that were replaced with a stub.
    """
    tool_indexes = [
        i
        for i, m in enumerate(messages)
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
        if tool_name in NON_COMPACTABLE_TOOLS:
            continue
        result[i] = {**msg, "content": TOOL_RESULT_STUB}
        stubbed += 1
    return result, stubbed


# Path-keyed readers: an older result for the same path is stale once a newer
# read of that path appears (e.g. the file was re-read after an edit), so the
# older one is safe to drop. Search/listing tools are excluded — their key is
# the query, not a single path, and dropping them is riskier.
SUPERSEDABLE_READ_TOOLS = frozenset(
    {
        "read_file",
        "read_document",
        "inspect_file",
        "file_info",
    }
)
SUPERSEDED_READ_STUB = (
    "[Earlier read of {path} cleared — a newer read of it appears later in the "
    "conversation. Re-read it if you need this older version.]"
)


def _tool_meta_by_call_id(
    messages: list[dict[str, Any]],
) -> dict[str, tuple[str, dict[str, Any]]]:
    """Map each tool_call_id to its ``(tool_name, parsed-arguments)``."""
    meta: dict[str, tuple[str, dict[str, Any]]] = {}
    for msg in messages:
        for tc in msg.get("tool_calls") or []:
            call_id = tc.get("id")
            fn = tc.get("function") or {}
            name = fn.get("name")
            if not call_id or not name:
                continue
            raw_args = fn.get("arguments")
            if isinstance(raw_args, dict):
                args = raw_args
            else:
                try:
                    parsed = json.loads(raw_args) if raw_args else {}
                    args = parsed if isinstance(parsed, dict) else {}
                except (json.JSONDecodeError, TypeError):
                    args = {}
            meta[call_id] = (name, args)
    return meta


def prune_superseded_reads(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Stub every read of a path except the most recent one for that path.

    Runs regardless of context pressure: a stale duplicate read is pure waste,
    so clearing it keeps long, edit-heavy tasks lean without an LLM call.
    """
    meta = _tool_meta_by_call_id(messages)
    keyed: list[tuple[int, str]] = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        nm = meta.get(str(msg.get("tool_call_id")))
        if not nm:
            continue
        name, args = nm
        path = args.get("path")
        if name in SUPERSEDABLE_READ_TOOLS and path:
            keyed.append((i, f"{name}:{path}"))

    last_index_for_key: dict[str, int] = {key: i for i, key in keyed}
    result = list(messages)
    pruned = 0
    for i, key in keyed:
        if i == last_index_for_key[key]:
            continue  # keep the freshest read of this path
        msg = result[i]
        content = msg.get("content") or ""
        if len(content) <= MIN_STUB_CHARS or content == TOOL_RESULT_STUB:
            continue
        path = key.split(":", 1)[1]
        result[i] = {**msg, "content": SUPERSEDED_READ_STUB.format(path=path)}
        pruned += 1
    return result, pruned


def _render_transcript(messages: list[dict[str, Any]], max_chars: int) -> str:
    """Render messages as a plain-text transcript, truncating the oldest part to ``max_chars``."""
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
    """Split messages into ``(system, old, tail)`` for summarization.

    The split point is nudged back past any leading tool messages so a tool
    result is never separated from the assistant turn that requested it.

    Args:
        messages: The conversation history.
        keep_recent_messages: How many trailing messages to keep verbatim.

    Returns:
        A ``(system_msgs, old, tail)`` triple of message lists.
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]

    start = max(0, len(rest) - keep_recent_messages)
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
    """Replace old turns with a single LLM-generated summary message.

    Args:
        client: An LLM client exposing a ``chat`` method.
        messages: The conversation history.
        context_length: The model's context window in tokens.
        keep_recent_messages: How many trailing messages to keep verbatim.

    Returns:
        A new history (system + summary + recent tail), or ``None`` if there is
        nothing old to summarize or the summary call failed/produced no text.
    """
    system_msgs, old, tail = _split_for_summary(messages, keep_recent_messages=keep_recent_messages)
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
    except Exception:
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
    """Manage context pressure: prune stale reads, micro-compact, then summarize.

    Applies the cheapest effective layer first and only escalates to the costly
    LLM summary once the cheaper passes leave the history near the real ceiling.

    Args:
        history: The conversation history.
        client: An LLM client used for the optional summary step.
        context_length: The model's context window in tokens.
        summary_failures: Count of prior consecutive summary failures (used to
            stop retrying the LLM summary once it keeps failing).

    Returns:
        A ``(history, summary_failures, events)`` triple: the managed history,
        the updated failure count, and human-readable event strings describing
        what was done.
    """
    events: list[str] = []

    # Always drop stale duplicate reads first — cheap, lossless, and it keeps a
    # long edit-heavy task from carrying every prior version of a file. Keep the
    # original list identity when nothing was pruned (callers may rely on it).
    pruned_history, superseded = prune_superseded_reads(history)
    if superseded:
        history = pruned_history
        events.append(f"Context: cleared {superseded} superseded read(s) of re-read file(s).")

    if not should_compact(history, context_length, threshold_pct=MICRO_COMPACT_THRESHOLD_PCT):
        return history, summary_failures, events

    history, stubbed = micro_compact(history)
    if stubbed:
        events.append(f"Context: micro-compact cleared {stubbed} old tool result(s).")

    # Only reach for the expensive LLM summary once the cheaper pass leaves us
    # near the real ceiling — not at the proactive micro-compact threshold.
    if not should_compact(history, context_length, threshold_pct=SUMMARY_COMPACT_THRESHOLD_PCT):
        return history, summary_failures, events

    if summary_failures >= MAX_SUMMARY_FAILURES:
        return history, summary_failures, events

    summarized = summarize_history(client, history, context_length)
    if summarized is None:
        summary_failures += 1
        events.append("Context: automatic summary failed; mechanical trimming will be used.")
        return history, summary_failures, events

    before = conservative_estimate(history)
    after = conservative_estimate(summarized)
    events.append(f"Context: history summarized (~{before} → ~{after} estimated tokens).")
    return summarized, 0, events
