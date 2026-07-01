"""Compact, always-current progress digest for the round anchor.

On a long task, a model has to work out "what have I already done" on every round.
A strong model can reconstruct that from the transcript; a weak, small-context
one cannot — it drifts off the task, repeats finished work, ignores harness
rules, or gets stuck, precisely because the current state is buried under the
whole conversation it must re-read each round.

This module turns the tool evidence already collected this turn (the same
``EvidenceLedger`` the groundedness gate uses) into a short, high-signal state
block. The loop re-injects it near the end of the prompt every round, so the
model can rely on this digest instead of re-scanning history — the persistent-
working-memory pattern the frontier agent harnesses use. It is purely mechanical
(no LLM call), it is stripped and rebuilt each round (so it never accumulates),
and it lets the cheaper compaction passes stub the raw tool output more
aggressively without the model losing the thread.
"""

from __future__ import annotations

from ci2lab.harness.grounding_review.evidence import EvidenceLedger, ToolEvidence
from ci2lab.harness.tools.capabilities import FILE_WRITE_TOOLS

# Keep the digest small: it is a pointer to state, not a second transcript.
_MAX_PATHS = 8
_MAX_COMMANDS = 5
_MAX_INSPECTED = 6
_MAX_COMMAND_CHARS = 80

_READ_TOOLS = frozenset({"read_file", "read_document", "inspect_file", "file_info"})
_SEARCH_TOOLS = frozenset({"grep", "glob", "ls", "tree"})
_RUNTIME_TOOLS = frozenset({"bash", "git_status", "git_diff"})

PROGRESS_HEADER = "Progress so far this turn (build on it; do not repeat finished work):"


def _first(evidence: ToolEvidence, *keys: str) -> str:
    """Return the first present, non-empty string argument among ``keys``."""
    args = evidence.arguments
    for key in keys:
        value = args.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _dedupe(items: list[str], *, limit: int) -> list[str]:
    """Order-preserving de-duplication of non-empty strings, capped at ``limit``."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        item = item.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _short(text: str, limit: int) -> str:
    """Collapse whitespace and truncate ``text`` to ``limit`` characters."""
    collapsed = " ".join(str(text or "").split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def progress_digest(ledger: EvidenceLedger) -> str:
    """Build a compact progress digest from this turn's tool evidence.

    Args:
        ledger: The evidence ledger accumulated during the current turn.

    Returns:
        A short, multi-line state block (headed by :data:`PROGRESS_HEADER`), or
        an empty string when no tool work has happened yet.
    """
    records = ledger.records
    if not records:
        return ""

    written: list[str] = []
    commands: list[str] = []
    inspected: list[str] = []
    last_failure = ""

    for record in records:
        name = record.tool_name
        if not record.ok:
            # Keep only the most recent failure so the model stops retrying it
            # without turning the digest into an error log.
            reason = _short(record.content, 100)
            last_failure = f"{name}: {reason}" if reason else name
            continue
        if name in FILE_WRITE_TOOLS:
            path = _first(record, "path", "file", "filename")
            written.append(path or name)
        elif name == "bash":
            command = _first(record, "command", "cmd", "script")
            commands.append(_short(command, _MAX_COMMAND_CHARS) if command else "bash")
        elif name in _RUNTIME_TOOLS:
            commands.append(name)
        elif name in _READ_TOOLS or name in _SEARCH_TOOLS:
            inspected.append(_first(record, "path", "pattern", "query", "file") or name)

    lines: list[str] = []
    written = _dedupe(written, limit=_MAX_PATHS)
    if written:
        lines.append(f"- Wrote/edited: {', '.join(written)}")
    commands = _dedupe(commands, limit=_MAX_COMMANDS)
    if commands:
        lines.append(f"- Ran: {', '.join(commands)}")
    inspected = _dedupe(inspected, limit=_MAX_INSPECTED)
    if inspected:
        lines.append(f"- Inspected: {', '.join(inspected)}")
    if last_failure:
        lines.append(f"- Most recent failure (do not blindly retry): {_short(last_failure, 140)}")

    if not lines:
        return ""
    return f"{PROGRESS_HEADER}\n" + "\n".join(lines)
