"""Deterministic pre-orchestration intent classifier.

Architectural reference (concepts only, no code imported)
---------------------------------------------------------
Healthy agent frameworks (NVIDIA NeMo / AI-Q / Guardrails among them) keep
routing decisions in separate dimensions instead of one tangled check:

1. input classification   -> what does the user *want*?
2. workflow routing       -> which phases should run?
3. tool/write permissions -> is writing allowed, and where?
4. execution              -> run the chosen phases.
5. output validation/trace-> the orchestrator records the decision.

We adopt that *separation of concerns* only. CI2Lab deliberately stays small,
local, and deterministic, so this stays a tiny rule-based classifier:

* no LLM call,
* no filesystem access,
* no network access,
* no third-party framework dependency,
* output depends only on ``user_prompt``.

Two decision surfaces live here:

* ``classify_multiagent_intent`` -> ``MultiAgentIntentDecision`` is the *legacy*
  routing surface the orchestrator already consumes. Its behaviour is frozen so
  existing wiring and tests keep working.
* ``classify_orchestration_decision`` -> ``OrchestrationDecision`` is the new,
  *richer* surface. It separates the orchestration concerns explicitly —
  semantic task type, required capabilities, operational risk, allowed phases,
  and whether human confirmation is needed — instead of a single tangled flag.

Crucially, ``intent.py`` does **not** make the final security decision. It only
*proposes* capabilities and risk. The real, per-tool-call permission check still
lives in the execution gate. ``OrchestrationDecision.needs_confirmation`` and
``risk_level`` are advisory inputs to that gate, never a substitute for it.

For this first minimal phase the new surface is built *on top of* the proven
legacy routing (it reuses it as a backbone and enriches it). A later phase will
invert the dependency, making ``OrchestrationDecision`` the single source of
truth and reducing ``classify_multiagent_intent`` to a thin compatibility
adapter — see ``_to_legacy`` style mapping notes below.

The P0 fix this enables: distinguishing an explicit *write* request that merely
limits its scope (``"create X ... do not touch other files"``) from a *global*
no-write request (``"review only, do not edit anything"``). The former is a
write task; the latter is review-only. They must never be conflated.

Decision priority for the code domain (highest first):

    explicit write intent  >  scope constraint  >  global no-write (review-only)
"""

from __future__ import annotations

import re
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
    PAPER_REVIEW = "paper_review"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MultiAgentIntentDecision:
    """Routing decision derived purely from the user prompt.

    Legacy/compatibility surface. New code should prefer
    :class:`OrchestrationDecision`; this stays for the orchestrator wiring that
    already consumes it.
    """

    intent: MultiAgentIntent
    requires_write: bool
    allowed_phases: list[str]
    reason: str
    confidence: Confidence


# --- Rich orchestration decision (new surface) ----------------------------
#
# These dimensions are kept *separate on purpose*:
#   * task_type            -> semantic intent of the task
#   * required_capabilities-> what the task would need to be able to do
#   * risk_level           -> operational risk of letting it run
#   * allowed_phases       -> which orchestration phases may run
#   * needs_confirmation   -> should a human confirm before proceeding
#   * reasons              -> human-readable justification trail
#
# None of these *grant* anything. The execution gate still authorizes each
# tool call. ``risk_level`` never produces ``"blocked"`` here: intent.py does
# not block; it only flags. ``"blocked"`` is reserved for the gate's vocabulary.

TaskType = Literal[
    "meta",
    "review",
    "research",
    "document_summary",
    "code_change",
    "file_operation",
    "dangerous_operation",
    "ambiguous",
]

Capability = Literal[
    "read_fs",
    "write_fs",
    "edit_code",
    "run_shell",
    "network",
    "delete_fs",
]

RiskLevel = Literal["low", "medium", "high", "blocked"]


@dataclass(frozen=True)
class OrchestrationDecision:
    """Rich, multi-dimensional pre-orchestration decision.

    Produced by :func:`classify_orchestration_decision`. It describes *what the
    task is* and *what it would need*, but deliberately does not decide final
    execution permission — that stays in the execution gate, per tool call.
    """

    task_type: TaskType
    required_capabilities: frozenset[Capability]
    risk_level: RiskLevel
    allowed_phases: tuple[str, ...]
    needs_confirmation: bool
    reasons: tuple[str, ...]


# Canonical phase plans. Phase names are generic placeholders; the orchestrator
# resolves ``"coder"`` to a concrete implementer role at execution time.
_FULL_FLOW = ["planner", "researcher", "coder", "validator", "reviewer"]
_REVIEW_FLOW = ["planner", "researcher", "reviewer"]
_RESEARCH_REVIEW_FLOW = ["researcher", "reviewer"]
# Read a document AND produce output from it (e.g. "read the pdf and write the
# answer to a file"): research reads, a coder writes, a reviewer checks. No
# planner — a document task does not need one, and a toolless planner only
# stalls on it.
_RESEARCH_WRITE_FLOW = ["researcher", "coder", "reviewer"]

# Scientific peer-review pipeline. Read-only, grounded lenses run in sequence and
# the revision planner assembles only verified findings. Resolved and executed by
# the orchestrator's paper-review branch, not the generic phase loop.
_PAPER_REVIEW_FLOW = [
    "intake_reviewer",
    "scope_reviewer",
    "novelty_reviewer",
    "methodology_reviewer",
    "field_expert_reviewer",
    "adversarial_reviewer",
    "format_reviewer",
    "groundedness_verifier",
    "revision_planner",
]


# Scientific peer-review requests. Checked first so a paper review is not
# mis-routed to the generic code review-only / read-only plans.
_PAPER_REVIEW_MARKERS = (
    "peer review",
    "peer-review",
    "review this paper",
    "review the paper",
    "review this manuscript",
    "review the manuscript",
    "review my paper",
    "review my manuscript",
    "referee report",
    "review for a journal",
    "review for the journal",
    "review for a conference",
)

# --- Dimension 3: write-permission signals --------------------------------
#
# These three marker families are kept deliberately separate so the classifier
# never mixes "do not touch *other* files" (a scope limit) with "do not touch
# *anything*" (a global no-write). That conflation was the P0 bug.

# Global no-write / review-only blockers: writing is forbidden *entirely*.
# Note: only unambiguously global phrases live here. Scope-limited phrases such
# as "do not edit anything else" must NOT appear, or they would falsely block a
# legitimate scoped write task.
_GLOBAL_NO_WRITE_MARKERS = (
    "review-only",
    "review only",
    "only review",
    "only inspect",
    "only analyze",
    "without changing",
    "solo revisar",
    "solo revisa",
    "solo analiza",
    "solo análisis",
    "solo analisis",
    "do not implement",
    "don't implement",
    "no implementes",
    "no implementar",
    "do not write",
    "no escribas",
    "do not edit files",
    "do not edit any file",
    "do not edit any files",
    "do not modify files",
    "do not modify any file",
    "do not change files",
    "no edites nada",
    "no modifiques nada",
    "no cambies nada",
    "no toques nada",
    "no edites archivos",
    "no modifiques archivos",
    "no cambies archivos",
)

# Scope constraints: writing is allowed, but only within a limited surface.
# These restrict *which* files may change; they never forbid writing outright.
_SCOPE_CONSTRAINT_MARKERS = (
    "ningún otro archivo",
    "ningun otro archivo",
    "ningún otro fichero",
    "ningun otro fichero",
    "otros archivos",
    "otro archivo",
    "otros ficheros",
    "demás archivos",
    "demas archivos",
    "demás ficheros",
    "demas ficheros",
    "unrelated file",
    "unrelated files",
    "other file",
    "other files",
    "any other file",
    "anything else",
    "nothing else",
)

# Positive write verbs (create / persist / modify). Matched per clause and only
# when not negated, so "implement this fix" counts but "do not implement" does
# not. Document-domain prompts are handled separately above this dimension.
_WRITE_VERBS = (
    "crea",
    "crear",
    "create",
    "escribe",
    "escribir",
    "write",
    "genera",
    "generar",
    "generate",
    "guarda",
    "guárda",
    "guardar",
    "save",
    "añade",
    "anade",
    "agrega",
    "agregar",
    "add",
    "implementa",
    "implementar",
    "implement",
    "arregla",
    "arreglar",
    "corrige",
    "fix",
    "modifica",
    "modificar",
    "modify",
    "edita",
    "editar",
    "edit",
    "cambia",
    "cambiar",
    "change",
    "actualiza",
    "actualizar",
    "update",
)

# Negation tokens that, when present in the same clause, cancel a write verb.
_NEGATION_TOKENS = (
    "no ",
    "not ",
    "n't",
    "do not",
    "don't",
    "never ",
    "sin ",
    "without ",
    "ningún",
    "ningun",
    "nunca ",
)

# Clause boundaries used to scope negation locally (so "create X but do not edit
# Y" splits the positive create away from the negated edit).
_CLAUSE_SPLIT = re.compile(r"[.;,\n]|\bbut\b|\bpero\b|\baunque\b|\bhowever\b")

# Asking to read/summarize a PDF or document (English and Spanish phrasings).
_DOCUMENT_SUMMARY_MARKERS = (
    "summarize pdf",
    "summarize the pdf",
    "summarize document",
    "summarize the document",
    "read pdf",
    "read the pdf",
    "read the document",
    "summary of the",
    "resume el pdf",
    "resúmeme el pdf",
    "resumeme el pdf",
    "leer pdf",
    "lee el pdf",
    "lee el documento",
    "resumen",
    "resúmelo",
    "resumelo",
)

# Asking to convert/export/create a document artifact.
_DOCUMENT_TRANSFORM_MARKERS = (
    "docx to pdf",
    "convert to pdf",
    "export to pdf",
    "export as pdf",
    "save as pdf",
    "convert document",
)

_DOCUMENT_ARTIFACT_MARKERS = (
    "pptx",
    "powerpoint",
    "presentation",
    "presentaci\u00f3n",
    "presentaciÃ³n",
    "presentacion",
    "diapositivas",
    "slides",
    "deck",
)

_DOCUMENT_SOURCE_TO_ARTIFACT_MARKERS = (
    "from pdf",
    "from document",
    "from a document",
    "a partir del pdf",
    "a partir de un pdf",
    "a partir de una pdf",
    "a partir de este documento",
    "a partir del documento",
    "a partir de un documento",
    "a partir de una fuente",
    "a partir de",
    "desde pdf",
    "desde un pdf",
    "desde el pdf",
    "desde documento",
    "desde un documento",
    "desde el documento",
    "pdf local",
    "local pdf",
    "documento local",
    "archivo local",
    "local document",
    "local file",
)
_LOCAL_DOCUMENT_PATH_RE = re.compile(r"\.(?:pdf|docx|pptx|md|txt)\b", re.IGNORECASE)
_CODE_CONTEXT_MARKERS = (
    ".py",
    "script",
    "python",
    "codigo",
    "cÃ³digo",
    "code",
    "bug",
    "test",
    "tests",
)

# Asking for explanation/analysis without file changes. Note: bare "analiza"
# is intentionally absent — "solo analiza" is a global no-write (review-only)
# marker, and a standalone "analiza" would shadow that distinction.
_READ_ONLY_MARKERS = (
    "explain",
    "what does it mean",
    "what does",
    "without editing",
    "explícame",
    "explicame",
    "explica",
    "qué significa",
    "que significa",
    "sin editar",
    "sin modificar",
    "solo leer",
    "read only",
    "read-only",
)

# Asking to implement/fix/modify code, or to produce/complete something. These
# are all write-intent verbs: a false positive only adds a coder phase, while a
# false negative leaves the task with no way to produce output at all.
_CODE_CHANGE_MARKERS = (
    "implement",
    "fix",
    "modify",
    "add",
    "change",
    "edit",
    "complete",
    "solve",
    "create",
    "write",
    "make",
    "generate",
    "build",
    "develop",
)

# Markers signalling an explicit request to persist output to a file.
_WRITE_REQUEST_MARKERS = (
    ".txt",
    ".md",
    ".csv",
    ".json",
    "save",
    "write to file",
    "export",
)


# --- New dimensions for the rich OrchestrationDecision --------------------
#
# Destructive verbs. Like write verbs, these are matched per clause and only
# when the clause is not negated, so "do not delete" / "no borres" do not flag.
_DESTRUCTIVE_VERBS = (
    "borra",
    "borrar",
    "elimina",
    "eliminar",
    "suprime",
    "suprimir",
    "delete",
    "remove",
    "drop ",
    "wipe",
    "purge",
    "resetea",
    "resetear",
    "reset",
    "limpia",
    "limpiar",
    "clean",
    "vacía",
    "vacia",
    "vaciar",
    "trunca",
    "truncar",
    "rm -rf",
    "rm -r",
    "rm ",
)

# Destructive operations that imply a shell (so run_shell is required too).
_SHELL_DELETE_MARKERS = (
    "rm -rf",
    "rm -r",
    "rm ",
    "del ",
    "rmdir",
    "drop table",
    "truncate",
)

# A standalone file artifact is being created/persisted (not source-code edit).
# Code targets such as ``.py`` are intentionally absent: editing code is a
# code_change, while persisting a ``.txt``/``.md`` blob is a file_operation.
_FILE_CREATION_MARKERS = (
    "crea un archivo",
    "crea el archivo",
    "crea un fichero",
    "crea otro archivo",
    "crear un archivo",
    "crear archivo",
    "crear un fichero",
    "create a file",
    "create the file",
    "create file",
    "create a new file",
    "nuevo archivo",
    "nuevo fichero",
    "new file",
    "archivo nuevo",
    "archivo llamado",
    "fichero llamado",
    "file named",
    "file called",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".log",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
)

# Light capability hints (additive). These never change the task_type; they
# only enrich required_capabilities so the gate sees a fuller picture.
_SHELL_CAPABILITY_MARKERS = (
    "pytest",
    "bash",
    "shell",
    "comando",
    "command",
    "ejecuta",
    "ejecutar",
    "run the",
    "git ",
    "npm ",
    "terminal",
)

_NETWORK_CAPABILITY_MARKERS = (
    "http://",
    "https://",
    "www.",
    "descarga",
    "descargar",
    "download",
    "fetch",
    "api ",
    "url",
    "endpoint",
    "request to",
)

# Questions about the agent/system itself, not about the codebase.
_META_MARKERS = (
    "qué puedes hacer",
    "que puedes hacer",
    "what can you do",
    "what are your tools",
    "list your tools",
    "tus herramientas",
    "qué herramientas",
    "que herramientas",
    "cómo funcionas",
    "como funcionas",
    "quién eres",
    "quien eres",
    "who are you",
    "what are you",
)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    """Return ``True`` if any marker in ``markers`` is a substring of ``text``."""
    return any(marker in text for marker in markers)


def _clauses(text: str) -> list[str]:
    """Split ``text`` into clauses so negation can be scoped locally."""
    return [clause.strip() for clause in _CLAUSE_SPLIT.split(text) if clause.strip()]


def has_explicit_write_intent(text: str) -> bool:
    """Dimension 3a: does the user positively ask to create/persist/modify?

    A write verb only counts inside a clause that is not itself negated, so
    ``"implement this fix"`` is a write but ``"do not implement"`` is not. This
    is what lets a scoped write request survive a trailing ``"do not touch
    other files"`` clause.
    """
    for clause in _clauses(text):
        if _contains_any(clause, _NEGATION_TOKENS):
            continue
        if _contains_any(clause, _WRITE_VERBS):
            return True
    return False


def has_global_no_write(text: str) -> bool:
    """Dimension 3b: is writing forbidden *entirely* (review-only)?"""
    return _contains_any(text, _GLOBAL_NO_WRITE_MARKERS)


def has_scope_constraint(text: str) -> bool:
    """Dimension 3c: is writing limited to a subset of files (scope limit)?"""
    return _contains_any(text, _SCOPE_CONSTRAINT_MARKERS)


def classify_multiagent_intent(user_prompt: str) -> MultiAgentIntentDecision:
    """Classify ``user_prompt`` into a deterministic routing decision.

    The decision separates input classification from write permissions:

    * scientific peer-review requests are routed first (read-only lenses);
    * document-domain prompts (summarize / transform) own their write semantics
      and are routed next;
    * for the code domain the priority is, highest first,
      ``explicit write > scope constraint > global no-write (review-only)``;
    * read/analysis and a safe read-mostly fallback close out the chain.

    A scope constraint ("do not touch other files") never forces review-only —
    that was the P0 bug. Only a *global* no-write does.
    """
    text = (user_prompt or "").lower()

    # Scientific peer review is routed first so it is never mis-classified as a
    # generic code review or read-only answer.
    if _contains_any(text, _PAPER_REVIEW_MARKERS):
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.PAPER_REVIEW,
            requires_write=False,
            allowed_phases=list(_PAPER_REVIEW_FLOW),
            reason="Prompt asks for a scientific peer review of a manuscript.",
            confidence="high",
        )

    # Dimension 3 is computed once, up front, then consumed by the routing rules.
    explicit_write = has_explicit_write_intent(text)
    global_no_write = has_global_no_write(text)
    scope_constraint = has_scope_constraint(text)

    # --- Document domain first (its own read/write semantics) --------------
    if _contains_any(text, _DOCUMENT_SUMMARY_MARKERS):
        # "read the pdf and write/solve/complete ..." needs an implementer too —
        # a file output marker or an explicit (non-negated) write verb means a
        # coder must run.
        requires_write = explicit_write or _contains_any(text, _WRITE_REQUEST_MARKERS)
        reason = "Prompt asks to read/summarize a document."
        if requires_write:
            reason += " It also asks to produce output, so an implementer is included."
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.DOCUMENT_SUMMARY,
            requires_write=requires_write,
            allowed_phases=list(_RESEARCH_WRITE_FLOW if requires_write else _RESEARCH_REVIEW_FLOW),
            reason=reason,
            confidence="high",
        )

    document_artifact_requested = _contains_any(text, _DOCUMENT_ARTIFACT_MARKERS)
    source_backed_artifact = document_artifact_requested and (
        _contains_any(text, _DOCUMENT_SOURCE_TO_ARTIFACT_MARKERS)
        or bool(_LOCAL_DOCUMENT_PATH_RE.search(text))
    ) and not _contains_any(text, _CODE_CONTEXT_MARKERS)
    if _contains_any(text, _DOCUMENT_TRANSFORM_MARKERS) or source_backed_artifact:
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.DOCUMENT_TRANSFORM,
            requires_write=True,
            allowed_phases=list(_FULL_FLOW),
            reason="Prompt asks to convert/export/create a document artifact.",
            confidence="high",
        )

    # --- Code domain: explicit write beats a scope constraint, which in turn
    #     beats a global no-write (review-only). ------------------------------
    if explicit_write and not global_no_write:
        if scope_constraint:
            reason = (
                "Prompt explicitly asks to create/modify a file and only limits "
                "its scope to other files; this is a write task, not review-only."
            )
        else:
            reason = "Prompt explicitly asks to create, modify, or persist a file."
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.CODE_CHANGE,
            requires_write=True,
            allowed_phases=list(_FULL_FLOW),
            reason=reason,
            confidence="high",
        )

    # Read/analysis intent (no file changes) is checked before review-only so a
    # genuine "read and explain" prompt is not mislabeled as a code review.
    if _contains_any(text, _READ_ONLY_MARKERS) and not explicit_write:
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.READ_ONLY_ANSWER,
            requires_write=False,
            allowed_phases=list(_RESEARCH_REVIEW_FLOW),
            reason="Prompt asks for explanation/analysis without changing files.",
            confidence="high",
        )

    if global_no_write:
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.REVIEW_ONLY,
            requires_write=False,
            allowed_phases=list(_REVIEW_FLOW),
            reason="Prompt globally forbids writing (review-only / do-not-edit-anything).",
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

    # A scope constraint on its own still implies the user wants an edit, just a
    # bounded one — route it as a (medium-confidence) write task, never as
    # review-only.
    if scope_constraint:
        return MultiAgentIntentDecision(
            intent=MultiAgentIntent.CODE_CHANGE,
            requires_write=True,
            allowed_phases=list(_FULL_FLOW),
            reason="Prompt limits which files may change, implying a scoped write task.",
            confidence="medium",
        )

    return MultiAgentIntentDecision(
        intent=MultiAgentIntent.UNKNOWN,
        requires_write=False,
        allowed_phases=list(_REVIEW_FLOW),
        reason="No decisive intent markers found; defaulting to a safe read-mostly plan.",
        confidence="low",
    )


# --- Rich orchestration decision ------------------------------------------

_FULL_FLOW_PHASES = tuple(_FULL_FLOW)
_REVIEW_FLOW_PHASES = tuple(_REVIEW_FLOW)
_RESEARCH_REVIEW_PHASES = tuple(_RESEARCH_REVIEW_FLOW)


def has_dangerous_operation(text: str) -> bool:
    """Dimension: does the user ask for a destructive filesystem operation?

    A destructive verb only counts inside a non-negated clause, so
    ``"no borres nada"`` / ``"do not delete"`` do not flag, mirroring how
    :func:`has_explicit_write_intent` scopes negation locally.
    """
    for clause in _clauses(text):
        if _contains_any(clause, _NEGATION_TOKENS):
            continue
        if _contains_any(clause, _DESTRUCTIVE_VERBS):
            return True
    return False


def _is_file_creation(text: str) -> bool:
    """Distinguish persisting a standalone file from editing source code."""
    return _contains_any(text, _FILE_CREATION_MARKERS)


def classify_orchestration_decision(user_prompt: str) -> OrchestrationDecision:
    """Classify ``user_prompt`` into a rich :class:`OrchestrationDecision`.

    The decision separates orchestration concerns explicitly and never grants
    final permission. ``risk_level``/``needs_confirmation`` are advisory inputs
    to the execution gate, which still authorizes each tool call.

    Routing order (highest priority first):

    1. *destructive* operations dominate — high risk, confirmation required;
    2. a genuine *contradiction* (explicit write **and** a global no-write ban)
       is surfaced as ``ambiguous`` rather than silently resolved;
    3. *meta* questions about the agent itself;
    4. everything else is seeded from the proven legacy routing
       (:func:`classify_multiagent_intent`) and enriched with capabilities,
       risk, and a finer task type (``file_operation`` vs ``code_change``).
    """
    text = (user_prompt or "").lower()

    explicit_write = has_explicit_write_intent(text)
    global_no_write = has_global_no_write(text)
    dangerous = has_dangerous_operation(text)

    extra_caps: set[Capability] = set()
    if _contains_any(text, _SHELL_CAPABILITY_MARKERS):
        extra_caps.add("run_shell")
    if _contains_any(text, _NETWORK_CAPABILITY_MARKERS):
        extra_caps.add("network")

    # 1. Destructive filesystem operations: high risk, confirm before running.
    if dangerous:
        caps: set[Capability] = extra_caps | {"read_fs", "write_fs", "delete_fs"}
        if _contains_any(text, _SHELL_DELETE_MARKERS):
            caps.add("run_shell")
        return OrchestrationDecision(
            task_type="dangerous_operation",
            required_capabilities=frozenset(caps),
            risk_level="high",
            allowed_phases=_FULL_FLOW_PHASES,
            needs_confirmation=True,
            reasons=(
                "Prompt requests a destructive filesystem operation (delete/clean/reset/wipe).",
                "intent.py flags the risk and requests confirmation; the "
                "execution gate still authorizes each tool call.",
            ),
        )

    # 2. Genuine contradiction: explicit write AND a global no-write ban.
    if explicit_write and global_no_write:
        return OrchestrationDecision(
            task_type="ambiguous",
            required_capabilities=frozenset({"read_fs"}),
            risk_level="medium",
            allowed_phases=_REVIEW_FLOW_PHASES,
            needs_confirmation=True,
            reasons=(
                "Prompt both requests a write and globally forbids writing; "
                "the intent is contradictory.",
                "Defer to human confirmation before granting any write capability.",
            ),
        )

    # 3. Meta questions about the agent/system itself.
    if _contains_any(text, _META_MARKERS):
        return OrchestrationDecision(
            task_type="meta",
            required_capabilities=frozenset(),
            risk_level="low",
            allowed_phases=_RESEARCH_REVIEW_PHASES,
            needs_confirmation=False,
            reasons=("Prompt asks about the agent/system itself, not the codebase.",),
        )

    # 4. Seed from the proven legacy routing, then enrich.
    legacy = classify_multiagent_intent(user_prompt)
    phases = tuple(legacy.allowed_phases)
    reasons = (legacy.reason,)

    if legacy.intent is MultiAgentIntent.DOCUMENT_SUMMARY:
        caps = extra_caps | {"read_fs"}
        if legacy.requires_write:
            caps.add("write_fs")
        return OrchestrationDecision(
            task_type="document_summary",
            required_capabilities=frozenset(caps),
            risk_level="low",
            allowed_phases=phases,
            needs_confirmation=False,
            reasons=reasons,
        )

    if legacy.intent is MultiAgentIntent.DOCUMENT_TRANSFORM:
        return OrchestrationDecision(
            task_type="file_operation",
            required_capabilities=frozenset(extra_caps | {"read_fs", "write_fs"}),
            risk_level="medium",
            allowed_phases=phases,
            needs_confirmation=False,
            reasons=(*reasons, "Converting/exporting a document writes a new file artifact."),
        )

    if legacy.intent is MultiAgentIntent.REVIEW_ONLY:
        return OrchestrationDecision(
            task_type="review",
            required_capabilities=frozenset(extra_caps | {"read_fs"}),
            risk_level="low",
            allowed_phases=phases,
            needs_confirmation=False,
            reasons=reasons,
        )

    if legacy.intent is MultiAgentIntent.READ_ONLY_ANSWER:
        return OrchestrationDecision(
            task_type="research",
            required_capabilities=frozenset(extra_caps | {"read_fs"}),
            risk_level="low",
            allowed_phases=phases,
            needs_confirmation=False,
            reasons=reasons,
        )

    if legacy.intent is MultiAgentIntent.CODE_CHANGE:
        if _is_file_creation(text):
            return OrchestrationDecision(
                task_type="file_operation",
                required_capabilities=frozenset(extra_caps | {"read_fs", "write_fs"}),
                risk_level="medium",
                allowed_phases=phases,
                needs_confirmation=False,
                reasons=(*reasons, "Prompt creates/persists a standalone file."),
            )
        return OrchestrationDecision(
            task_type="code_change",
            required_capabilities=frozenset(extra_caps | {"read_fs", "write_fs", "edit_code"}),
            risk_level="medium",
            allowed_phases=phases,
            needs_confirmation=False,
            reasons=reasons,
        )

    # UNKNOWN -> safe, read-mostly research posture.
    return OrchestrationDecision(
        task_type="research",
        required_capabilities=frozenset(extra_caps | {"read_fs"}),
        risk_level="low",
        allowed_phases=phases,
        needs_confirmation=False,
        reasons=(*reasons, "No decisive intent markers; defaulting to a read-only posture."),
    )
