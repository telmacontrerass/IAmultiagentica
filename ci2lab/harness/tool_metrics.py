"""Tool-call correctness metrics: did the model call tools *correctly*?

Task-success benchmarks (Terminal-Bench, SWE-bench, the internal suite) grade the
final state, so they fuse tool-calling reliability with reasoning, planning and
coding. This module isolates the tool-calling axis: of every tool call the model
*attempted*, how many were well-formed, named a real tool, and carried valid
arguments?

**The denominator is the point.** A malformed call the parser could not read, and
a call naming a tool that does not exist, are the two failure modes small local
models hit most — and both are easy to leave out of the count, which silently
flatters the score. An attempt is therefore *any* point at which the model tried
to call a tool, including the ones that never reached execution.

**Raw vs effective.** ci2lab repairs some malformed payloads (e.g. arguments that
are not valid JSON) rather than failing the round. A repaired call executes and
looks identical to a clean one in the result, but only the clean one is a *model*
success. :attr:`ToolCallQuality.raw_correct` counts what the model got right on
its own; :attr:`ToolCallQuality.effective_correct` counts what the harness
ultimately dispatched. The gap between them is what the scaffolding contributed —
the quantity a "scaffolding, not fine-tuning" claim rests on.

Metric names follow the tool-calling literature (BFCL and related): *tool-selection*
(right tool name), *argument validity* (schema-valid arguments), *hallucinated tool*
(invented name), and *format/parse validity* (well-formed payload).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

__all__ = [
    "NON_ATTEMPT_OUTCOMES",
    "ToolCallQuality",
    "summarize_tool_calls",
]

NON_ATTEMPT_OUTCOMES = frozenset(
    {
        "already_satisfied",
        "skipped_after_error",
        "repeated_failure",
        "blocked_by_policy",
    }
)
"""Outcomes the harness synthesizes without the model attempting a call.

These are recorded as tool results so the model sees feedback, but no tool ran and
the model did not emit them this round. Counting them would corrupt the
denominator, so they are excluded from every rate below.
"""


@dataclass
class ToolCallQuality:
    """Tool-call correctness for one run.

    Attributes:
        attempts: Every tool call the model attempted, including ones that never
            executed (unparseable payloads and invented tool names).
        raw_correct: Attempts that were well-formed *as the model emitted them* —
            no harness repair, a known tool, and valid arguments.
        effective_correct: Attempts the harness successfully dispatched, counting
            those it had to repair first.
        repaired: Attempts that only became valid because the harness fixed them.
        malformed: Attempts whose payload could not be parsed at all.
        hallucinated_tool: Attempts naming a tool that does not exist.
        invalid_arguments: Attempts rejected by argument validation.
        execution_error: Well-formed, dispatched calls whose tool returned an
            error (often environmental — a missing file, a failing command —
            rather than a tool-calling mistake).
    """

    attempts: int = 0
    raw_correct: int = 0
    effective_correct: int = 0
    repaired: int = 0
    malformed: int = 0
    hallucinated_tool: int = 0
    invalid_arguments: int = 0
    execution_error: int = 0

    @property
    def raw_correctness_rate(self) -> float | None:
        """Share of attempts the model got right unaided, or ``None`` if no attempts."""
        return self.raw_correct / self.attempts if self.attempts else None

    @property
    def effective_correctness_rate(self) -> float | None:
        """Share of attempts the harness dispatched, or ``None`` if no attempts."""
        return self.effective_correct / self.attempts if self.attempts else None

    @property
    def repair_rate(self) -> float | None:
        """Share of attempts rescued by harness repair, or ``None`` if no attempts.

        This is the scaffolding's direct contribution to tool-calling reliability:
        calls the model got wrong that ran anyway.
        """
        return self.repaired / self.attempts if self.attempts else None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict including the derived rates."""
        data = asdict(self)
        data["raw_correctness_rate"] = self.raw_correctness_rate
        data["effective_correctness_rate"] = self.effective_correctness_rate
        data["repair_rate"] = self.repair_rate
        return data


def summarize_tool_calls(
    tool_entries: list[Any],
    parse_failures: list[Any],
) -> ToolCallQuality:
    """Aggregate tool-call correctness for one run.

    Args:
        tool_entries: Executed tool-call records (``ToolCallLogEntry``-shaped:
            ``ok``, ``outcome`` and ``repaired`` are read).
        parse_failures: Attempts that never reached execution
            (``ToolParseFailureEntry``-shaped: ``kind`` is read, one of
            ``"unparsed"`` or ``"unknown_tool"``).

    Returns:
        The aggregated :class:`ToolCallQuality` for the run.
    """
    quality = ToolCallQuality()

    for entry in tool_entries:
        outcome = getattr(entry, "outcome", None)
        if outcome in NON_ATTEMPT_OUTCOMES:
            # The harness synthesized this result; the model did not call anything.
            continue

        quality.attempts += 1
        was_repaired = bool(getattr(entry, "repaired", False))
        if was_repaired:
            quality.repaired += 1

        if outcome == "unknown_tool":
            quality.hallucinated_tool += 1
            continue
        if outcome == "invalid_arguments":
            quality.invalid_arguments += 1
            continue

        # The call named a real tool and passed argument validation, so it was
        # dispatched — whether or not the tool itself then succeeded.
        quality.effective_correct += 1
        if not was_repaired:
            quality.raw_correct += 1
        if not getattr(entry, "ok", True):
            quality.execution_error += 1

    for failure in parse_failures:
        quality.attempts += 1
        if getattr(failure, "kind", "unparsed") == "unknown_tool":
            quality.hallucinated_tool += 1
        else:
            quality.malformed += 1

    return quality
