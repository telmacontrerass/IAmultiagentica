"""Evidence collected during one agent turn.

The final-answer review is intentionally deterministic: it checks the answer
against the user's prompt plus real tool results, instead of asking another
model to decide whether the first model hallucinated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ci2lab.harness.tools.capabilities import MUTATING_TOOLS, READ_ONLY_TOOLS

_WS_RE = re.compile(r"\s+")


def _compact(text: str, *, limit: int = 4000) -> str:
    """Normalize whitespace and cap large tool outputs for review prompts."""
    compacted = _WS_RE.sub(" ", str(text or "")).strip()
    return compacted[:limit]


@dataclass(frozen=True)
class ToolEvidence:
    """One tool result that can ground a final answer."""

    tool_name: str
    arguments: dict[str, Any]
    content: str
    ok: bool
    outcome: str | None = None

    @property
    def arguments_text(self) -> str:
        """Stable, searchable representation of the tool arguments."""
        try:
            return json.dumps(self.arguments, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(self.arguments)


@dataclass
class EvidenceLedger:
    """Prompt and tool evidence available before a final answer is accepted."""

    user_prompt: str
    records: list[ToolEvidence] = field(default_factory=list)

    def add(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        content: str,
        *,
        ok: bool,
        outcome: str | None = None,
    ) -> None:
        """Record one tool result."""
        self.records.append(
            ToolEvidence(
                tool_name=tool_name,
                arguments=dict(arguments),
                content=str(content or ""),
                ok=ok,
                outcome=outcome,
            )
        )

    @property
    def successful_tools(self) -> set[str]:
        return {record.tool_name for record in self.records if record.ok}

    @property
    def has_read_evidence(self) -> bool:
        return any(record.ok and record.tool_name in READ_ONLY_TOOLS for record in self.records)

    @property
    def has_web_evidence(self) -> bool:
        return any(
            record.ok and record.tool_name in {"web_search", "web_fetch"} for record in self.records
        )

    @property
    def has_runtime_evidence(self) -> bool:
        return any(
            record.ok and record.tool_name in {"bash", "git_status", "git_diff"}
            for record in self.records
        )

    @property
    def has_mutation_evidence(self) -> bool:
        return any(record.ok and record.tool_name in MUTATING_TOOLS for record in self.records)

    @property
    def evidence_text(self) -> str:
        """Searchable text from the user prompt and successful tool results."""
        parts = [self.user_prompt]
        for record in self.records:
            if not record.ok:
                continue
            parts.append(record.tool_name)
            parts.append(record.arguments_text)
            parts.append(record.content)
        return "\n".join(parts)

    def summary(self, *, max_records: int = 12) -> str:
        """Human-readable evidence summary for model nudges and logs."""
        if not self.records:
            return "No tool evidence was collected in this turn."
        lines: list[str] = []
        for record in self.records[-max_records:]:
            status = "OK" if record.ok else "ERROR"
            args = _compact(record.arguments_text, limit=500)
            content = _compact(record.content, limit=700)
            lines.append(f"- [{status}] {record.tool_name} {args}: {content}")
        return "\n".join(lines)
