"""Deterministic pre-orchestration intent classifier.

Inspired by NVIDIA-style intent routing: classify the user request *before*
building or executing multi-agent phases, then use that decision to pick the
allowed phases and whether any write capability is needed.

The classifier is intentionally pure and deterministic:

* no LLM call,
* no filesystem access,
* no network access,
* output depends only on ``user_prompt``.

This keeps routing cheap, testable, and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

Confidence = Literal["high", "medium", "low"]


class MultiAgentIntent(str, Enum):
    """Coarse intent categories used to route the orchestrator."""

    CODE_CHANGE = "code_change"
    REVIEW_ONLY = "review_only"
    READ_ONLY_ANSWER = "read_only_answer"
    DOCUMENT_TRANSFORM = "document_transform"
    DOCUMENT_SUMMARY = "document_summary"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MultiAgentIntentDecision:
    """Routing decision derived purely from the user prompt."""

    intent: MultiAgentIntent
    requires_write: bool
    allowed_phases: list[str]
    reason: str
    confidence: Confidence


# Canonical phase plans. Phase names are generic placeholders; the orchestrator
# resolves ``"coder"`` to a concrete implementer role at execution time.
_FULL_FLOW = ["planner", "researcher", "coder", "validator", "reviewer"]
_REVIEW_FLOW = ["planner", "researcher", "reviewer"]
_RESEARCH_REVIEW_FLOW = ["researcher", "reviewer"]


# Explicit negative constraints / review-only blockers. These must beat any
# positive implementation wording (e.g. "implement ... but do not edit").
_REVIEW_ONLY_MARKERS = (
    "review-only",
    "review only",
    "do not implement",
    "do not edit",
    "do not modify",
    "no cambies archivos",
    "no cambies",
    "no edites",
    "no modifiques",
    "solo analiza",
    "solo revisar",
    "solo revisa",
    "only inspect",
)

# Asking to read/summarize a PDF or document.
_DOCUMENT_SUMMARY_MARKERS = (
    "resume el pdf",
    "resúmeme el pdf",
    "resumeme el pdf",
    "summarize pdf",
    "summarize the pdf",
    "leer pdf",
    "lee el pdf",
    "lee el documento",
    "resumen",
    "resúmelo",
    "resumelo",
    "summarize document",
    "summarize the document",
)

# Asking to convert/export a document.
_DOCUMENT_TRANSFORM_MARKERS = (
    "convertir docx a pdf",
    "docx to pdf",
    "docx a pdf",
    "convertir a pdf",
    "exportar",
    "export to pdf",
    "export as pdf",
    "guardar como pdf",
    "save as pdf",
    "convert document",
)

# Asking for explanation/analysis without file changes.
_READ_ONLY_MARKERS = (
    "explícame",
    "explicame",
    "analiza",
    "qué significa",
    "que significa",
    "sin editar",
    "solo leer",
    "read only",
    "read-only",
)

# Asking to implement/fix/modify code.
_CODE_CHANGE_MARKERS = (
    "implementa",
    "implementar",
    "implement",
    "arregla",
    "arreglar",
    "modifica",
    "modificar",
    "añade",
    "anade",
    "fix",
    "change",
    "edit",
)

# Markers signalling an explicit request to persist output to a file.
_WRITE_REQUEST_MARKERS = (
    ".txt",
    ".md",
    ".csv",
    ".json",
    "guarda",
    "guárda",
    "guardar",
    "save",
    "write to file",
    "escribe en",
    "export",
    "exporta",
)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def classify_multiagent_intent(user_prompt: str) -> MultiAgentIntentDecision:
    """Classify ``user_prompt`` into a deterministic routing decision.

    Priority order (highest first):

    1. ``review_only``  - explicit "do not implement / edit" style blockers.
    2. ``document_summary`` - read/summarize a PDF or document.
    3. ``document_transform`` - convert/export a document.
    4. ``read_only_answer`` - explanation/analysis without file changes.
    5. ``code_change`` - implement/fix/modify code.
    6. ``unknown`` - safe read-mostly fallback.

    Explicit negative constraints always beat positive implementation words.
    """
    text = (user_prompt or "").lower()

    if _contains_any(text, _REVIEW_ONLY_MARKERS):
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.REVIEW_ONLY,
            requires_write=False,
            allowed_phases=list(_REVIEW_FLOW),
            reason="Prompt contains an explicit review-only / do-not-implement constraint.",
            confidence="high",
        )

    if _contains_any(text, _DOCUMENT_SUMMARY_MARKERS):
        requires_write = _contains_any(text, _WRITE_REQUEST_MARKERS)
        reason = "Prompt asks to read/summarize a document."
        if requires_write:
            reason += " It also asks to persist the summary to a file."
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.DOCUMENT_SUMMARY,
            requires_write=requires_write,
            allowed_phases=list(_RESEARCH_REVIEW_FLOW),
            reason=reason,
            confidence="high",
        )

    if _contains_any(text, _DOCUMENT_TRANSFORM_MARKERS):
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.DOCUMENT_TRANSFORM,
            requires_write=True,
            allowed_phases=list(_FULL_FLOW),
            reason="Prompt asks to convert/export a document into another format.",
            confidence="high",
        )

    if _contains_any(text, _READ_ONLY_MARKERS):
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.READ_ONLY_ANSWER,
            requires_write=False,
            allowed_phases=list(_RESEARCH_REVIEW_FLOW),
            reason="Prompt asks for explanation/analysis without changing files.",
            confidence="high",
        )

    if _contains_any(text, _CODE_CHANGE_MARKERS):
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.CODE_CHANGE,
            requires_write=True,
            allowed_phases=list(_FULL_FLOW),
            reason="Prompt asks to implement, fix, or modify code.",
            confidence="high",
        )

    return MultiAgentIntentDecision(
        intent=MultiAgentIntent.UNKNOWN,
        requires_write=False,
        allowed_phases=list(_REVIEW_FLOW),
        reason="No decisive intent markers found; defaulting to a safe read-mostly plan.",
        confidence="low",
    )
