"""Compute tool-call correctness for opencode from its own NDJSON trace.

The comparison ci2lab cares about is *at fixed model*, so the tool-call metric has
to mean the same thing for every harness. Harbor's ATIF trajectory cannot supply
it: ATIF has no tool-error field, and Harbor's opencode adapter drops opencode's
``status``/``error`` when it converts. opencode's own ``run --format json`` output
keeps them, so the honest source for opencode's KPI is opencode's own trace.

The NDJSON emits one ``tool_use`` event per completed *or* errored tool call, with
``part.tool`` (name), ``part.state.input`` (arguments) and ``part.state.status``
(``completed`` | ``error``). Failure classes are recovered from the error text,
which opencode prefixes distinctly:

* ``Unknown tool: <name>``      → the model invented a tool  → hallucinated_tool
* ``Invalid tool input: <...>`` → arguments failed the schema → invalid_arguments
* anything else                 → the tool ran and failed     → execution_error

Mapped onto the same :class:`~ci2lab.harness.tool_metrics.ToolCallQuality` ci2lab
reports, so both columns of the results table are computed the same way.

**Known asymmetry (disclose it, do not hide it).** opencode surfaces a malformed
payload as an errored tool call, whereas ci2lab may *repair* it and run it anyway.
``repaired`` is therefore always 0 here, and opencode's ``raw`` and ``effective``
correctness coincide. That difference is not noise — it is precisely the
scaffolding behaviour under study — but it means "repair rate" is a ci2lab-only
column, not a like-for-like comparison.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ci2lab.harness.tool_metrics import ToolCallQuality

__all__ = [
    "HALLUCINATED_TOOL_PREFIX",
    "INVALID_INPUT_PREFIX",
    "summarize_opencode_trace",
    "summarize_opencode_trace_file",
]

HALLUCINATED_TOOL_PREFIX = "Unknown tool:"
"""Error prefix opencode uses when the model names a tool that does not exist."""

INVALID_INPUT_PREFIX = "Invalid tool input:"
"""Error prefix opencode uses when arguments fail the tool's schema."""


def summarize_opencode_trace(events: list[dict[str, Any]]) -> ToolCallQuality:
    """Aggregate tool-call correctness from parsed opencode NDJSON events.

    Args:
        events: Decoded NDJSON records from ``opencode run --format json``.

    Returns:
        The aggregated :class:`ToolCallQuality`, directly comparable to ci2lab's.
    """
    quality = ToolCallQuality()

    for event in events:
        if event.get("type") != "tool_use":
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        state = part.get("state")
        state = state if isinstance(state, dict) else {}

        quality.attempts += 1
        if state.get("status") == "completed":
            # opencode does not repair payloads, so a dispatched call is one the
            # model emitted correctly: raw and effective correctness coincide.
            quality.effective_correct += 1
            quality.raw_correct += 1
            continue

        error = str(state.get("error") or "")
        if error.startswith(HALLUCINATED_TOOL_PREFIX):
            quality.hallucinated_tool += 1
        elif error.startswith(INVALID_INPUT_PREFIX):
            quality.invalid_arguments += 1
        else:
            # A real tool, validly called, that failed when it ran.
            quality.effective_correct += 1
            quality.raw_correct += 1
            quality.execution_error += 1

    return quality


def summarize_opencode_trace_file(path: Path) -> ToolCallQuality | None:
    """Read an opencode NDJSON trace and aggregate its tool-call correctness.

    Malformed lines are skipped rather than failing the whole trace: the file is
    written incrementally and a run killed by a timeout can leave a partial line.

    Args:
        path: The ``.ndjson`` trace written by ``opencode run --format json``.

    Returns:
        The aggregated quality, or ``None`` when the file is missing or unreadable.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)

    return summarize_opencode_trace(events)
