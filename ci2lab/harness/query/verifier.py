"""Opt-in completion verification.

After the agent reports a task as done, a fresh, independent subagent checks the
real workspace against the ORIGINAL user request — grading the work against
reality instead of against the agent's own summary. Following the pattern the
frontier coding harnesses use, the verifier:

* derives the concrete *acceptance criteria* implied by the request (task-
  agnostic — it works out what "done" means from the request itself),
* verifies each criterion against the actual workspace with read-only tools, and
* when running non-interactively, RUNS the project's own checks (tests, type
  checks, build, lint) with ``bash`` so the verdict is grounded in execution and
  not in the model's expectation.

It returns a STRUCTURED verdict (``passed`` / ``confidence`` / per-criterion /
``gaps``). The loop feeds any confirmed, actionable gaps back so the agent fixes
them before truly finishing, and keeps trying until the verdict passes, the gaps
stop changing (no progress), or the per-turn budget is spent.

Designed for mixed model strength:

* A strong model emits a high-confidence structured verdict with concrete gaps —
  real gating plus execution grounding.
* A weak model that rambles or is unsure is treated as a PASS: a ``low``-
  confidence verdict, a verdict with no actionable gap, or output we cannot parse
  as JSON never blocks the task (falling back to a strict first-line ``FAIL``
  check). This hardens capable agents without trapping weak ones in a false-
  reject loop.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.token_usage import TokenUsageState
from ci2lab.harness.types import AgentConfig

# Cap how many times verification may run per turn so a stubborn verifier cannot
# loop the task forever. Higher than a single retry so a capable model gets room
# to actually fix the confirmed gaps; the loop's no-progress guard stops it
# earlier when the same gaps keep coming back.
VERIFIER_MAX_PER_TURN = 3

# Confidence levels the verifier may report, most to least certain.
_CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})

# Only these confidence levels are allowed to block the task. ``low`` (and, by
# fallback, anything we cannot classify) leans PASS so a weak/uncertain verifier
# never stalls a genuinely-finished task.
_BLOCKING_CONFIDENCE = frozenset({"high", "medium"})


_VERIFIER_TASK_HEADER = (
    "You are an independent completion verifier. Another agent has just reported "
    "that it finished the user's request. Decide, from REAL evidence, whether "
    "every part of the request is genuinely done. Do not trust the agent's "
    "summary — check the actual workspace yourself.\n\n"
    "Original user request:\n"
    "<request>\n{request}\n</request>\n\n"
    "What the agent reports doing this turn:\n"
    "<actions>\n{actions}\n</actions>\n"
)

_VERIFIER_EVIDENCE_BLOCK = (
    "\nTool evidence collected this turn:\n<evidence>\n{evidence}\n</evidence>\n"
)

_VERIFIER_PREVIOUS_GAPS_BLOCK = (
    "\nThe previous verification attempt reported these gaps. Focus on whether "
    "they are now genuinely fixed:\n<previous_gaps>\n{previous_gaps}\n</previous_gaps>\n"
)

_VERIFIER_STEPS_READ_ONLY = (
    "\nDo this:\n"
    "1. Derive the concrete, checkable acceptance criteria implied by the request "
    "(what must be true for it to count as done). Keep them specific and minimal; "
    "do not invent requirements the user did not ask for.\n"
    "2. Independently verify each criterion against the ACTUAL workspace with your "
    "read-only tools. Open the files the agent claims to have written or edited "
    "and confirm the required content is really there.\n"
    "3. Judge ONLY against the request.\n"
)

_VERIFIER_STEPS_WITH_EXECUTION = (
    "\nDo this:\n"
    "1. Derive the concrete, checkable acceptance criteria implied by the request "
    "(what must be true for it to count as done). Keep them specific and minimal; "
    "do not invent requirements the user did not ask for.\n"
    "2. Independently verify each criterion against the ACTUAL workspace with your "
    "read-only tools. Open the files the agent claims to have written or edited "
    "and confirm the required content is really there.\n"
    "3. When the work is code and the project has its own checks that are relevant "
    "and safe to run (its test suite, type check, build, or lint), RUN them with "
    "`bash` and let the real result — not your expectation — drive the verdict. "
    "Only run non-destructive checks; never modify anything.\n"
    "4. Judge ONLY against the request.\n"
)

_VERIFIER_OUTPUT_CONTRACT = (
    "\nReturn ONLY a single JSON object, with no prose before or after it, in "
    "exactly this shape:\n"
    "{\n"
    '  "passed": true | false,\n'
    '  "confidence": "high" | "medium" | "low",\n'
    '  "criteria": [\n'
    '    {"criterion": "<short>", "met": true | false, "evidence": "<what you checked>"}\n'
    "  ],\n"
    '  "gaps": ["<specific, verifiable thing that must still be fixed>"]\n'
    "}\n\n"
    "Rules:\n"
    '- "passed" is true only if every criterion is genuinely met.\n'
    '- "gaps" must be empty when "passed" is true, and must list only real '
    "problems you actually confirmed.\n"
    '- If you are not sure a criterion failed, mark it met and set "confidence" '
    'to "low" — do not block the task on a guess.\n'
)


@dataclass(frozen=True)
class CriterionResult:
    """One acceptance criterion and whether the verifier confirmed it met."""

    criterion: str
    met: bool
    evidence: str = ""


@dataclass(frozen=True)
class VerificationVerdict:
    """Structured verdict returned by the completion verifier."""

    passed: bool
    confidence: str
    criteria: tuple[CriterionResult, ...] = ()
    gaps: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_actionable_failure(self) -> bool:
        """True only when this verdict should block the task and be fed back.

        A failure blocks only when the verifier is confident enough (``high`` or
        ``medium``) and it named at least one concrete gap. A ``low``-confidence
        failure, or a failure with no actionable gap, leans PASS.
        """
        return not self.passed and self.confidence in _BLOCKING_CONFIDENCE and bool(self.gaps)


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    """Interpret a JSON value (bool, number, or string) as a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return default
    return str(value).strip().lower() in {"true", "yes", "pass", "passed", "ok", "1"}


def _clean_str_list(value: Any) -> tuple[str, ...]:
    """Coerce a string or sequence into a tuple of trimmed, non-empty strings."""
    if isinstance(value, str):
        parts = [value]
    elif isinstance(value, (list, tuple)):
        parts = [str(part) for part in value]
    else:
        return ()
    return tuple(part.strip() for part in parts if part.strip())


def _parse_criteria(value: Any) -> tuple[CriterionResult, ...]:
    """Parse the ``criteria`` array of a verdict, skipping malformed entries."""
    if not isinstance(value, list):
        return ()
    results: list[CriterionResult] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = str(item.get("criterion") or item.get("text") or item.get("name") or "").strip()
        if not text:
            continue
        # Absent "met" leans met=True so a sloppy verdict does not invent a gap.
        met = _coerce_bool(item.get("met", item.get("passed")), default=True)
        results.append(
            CriterionResult(
                criterion=text,
                met=met,
                evidence=str(item.get("evidence") or "").strip(),
            )
        )
    return tuple(results)


def _try_load_object(text: str) -> dict[str, Any] | None:
    """Parse ``text`` as JSON and return a dict (last dict of a list), else None."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        for item in reversed(data):
            if isinstance(item, dict):
                return item
    return None


def _scan_last_object(text: str) -> dict[str, Any] | None:
    """Return the last balanced-brace ``{...}`` object that parses as JSON."""
    depth = 0
    start = -1
    last: dict[str, Any] | None = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    obj = _try_load_object(text[start : i + 1])
                    if obj is not None:
                        last = obj
                    start = -1
    return last


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of the verdict JSON object from model output.

    Weak models wrap JSON in prose or code fences, so try (in order) each fenced
    block, the whole string, a first-brace/last-brace slice, and finally a
    balanced-brace scan that prefers the last complete object (the verdict is
    usually emitted last).
    """
    text = text or ""
    candidates: list[str] = [
        block.strip() for block in re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    ]
    candidates.append(text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        obj = _try_load_object(candidate)
        if obj is not None:
            return obj
    return _scan_last_object(text)


def parse_verdict(text: str) -> VerificationVerdict | None:
    """Parse a structured verdict from verifier output, or None if there is none.

    Returns ``None`` when no verdict-shaped JSON object can be recovered, so the
    caller can fall back to the conservative unstructured check.
    """
    obj = _extract_json_object(text)
    if obj is None:
        return None
    # Guard against picking up an unrelated JSON object from the output.
    if not any(key in obj for key in ("passed", "criteria", "gaps")):
        return None

    passed = _coerce_bool(obj.get("passed"))
    confidence = str(obj.get("confidence") or "").strip().lower()
    if confidence not in _CONFIDENCE_LEVELS:
        # A structured verdict with no usable confidence is treated as medium so
        # a clearly-stated failure with gaps is not silently discarded.
        confidence = "medium"
    criteria = _parse_criteria(obj.get("criteria"))
    gaps = _clean_str_list(obj.get("gaps"))
    if not passed and not gaps:
        # Failure with no explicit gaps: harvest the unmet criteria as the gaps.
        gaps = tuple(item.criterion for item in criteria if not item.met)
    return VerificationVerdict(
        passed=passed,
        confidence=confidence,
        criteria=criteria,
        gaps=gaps,
    )


def _format_issues(verdict: VerificationVerdict) -> str:
    """Render a failing verdict's gaps as a bullet list for the fix message."""
    return "\n".join(f"- {gap}" for gap in verdict.gaps)


def _verdict_is_failure(output: str) -> bool:
    """Return ``True`` only when unstructured output's first line is a clear FAIL.

    This is the fallback for models that cannot emit the JSON verdict: only a
    first line that says ``FAIL`` (and not ``PASS``) counts, so a rambling weak
    model is treated as a pass rather than stalling the task forever.
    """
    text = (output or "").strip()
    if not text:
        return False  # no verdict -> do not block the task
    first_line = text.splitlines()[0].strip().upper()
    # Only a clear FAIL on the first line counts; "PASS" anywhere on that line
    # wins ties so an explained pass is never read as a failure.
    return "FAIL" in first_line and "PASS" not in first_line


def _build_task(
    *,
    request: str,
    actions: str,
    evidence: str,
    previous_gaps: str,
    allow_execution: bool,
) -> str:
    """Assemble the verifier subagent's task prompt for this turn."""
    task = _VERIFIER_TASK_HEADER.format(request=request.strip(), actions=actions)
    if evidence.strip():
        task += _VERIFIER_EVIDENCE_BLOCK.format(evidence=evidence.strip())
    if previous_gaps.strip():
        task += _VERIFIER_PREVIOUS_GAPS_BLOCK.format(previous_gaps=previous_gaps.strip())
    task += _VERIFIER_STEPS_WITH_EXECUTION if allow_execution else _VERIFIER_STEPS_READ_ONLY
    task += _VERIFIER_OUTPUT_CONTRACT
    return task


def verify_completion(
    config: AgentConfig,
    selection: ModelSelection,
    user_prompt: str,
    actions: list[str],
    *,
    evidence_summary: str = "",
    previous_gaps: str = "",
) -> str | None:
    """Independently verify task completion with a fresh subagent.

    Spawns a reviewer/validator subagent that derives the acceptance criteria
    from the original request and checks the real workspace against them, using
    isolated token accounting. When the run is non-interactive
    (``config.auto_confirm``), the subagent runs with the execution-capable
    ``VALIDATOR`` role so it can run the project's own tests/checks; otherwise it
    uses the read-only ``REVIEWER`` role to avoid surprise permission prompts.

    Deliberately conservative: it blocks only on a confident, actionable failure
    (see :meth:`VerificationVerdict.is_actionable_failure`), and leans toward
    passing when the verdict is unclear, unparseable, or the verifier could not
    run.

    Args:
        config: The active agent configuration (cloned with fresh token usage
            for the subagent).
        selection: The resolved model selection for the verifier subagent.
        user_prompt: The original user request to verify against.
        actions: Human-readable descriptions of what the agent reports doing
            this turn.
        evidence_summary: Optional summary of this turn's tool evidence, passed
            to the verifier as extra context (it still checks independently).
        previous_gaps: Gaps reported by the previous verification attempt, so the
            verifier can focus on whether they are now fixed.

    Returns:
        A bullet list of the concrete gaps to fix when the work clearly fails
        verification, or ``None`` when it passes, the verdict is unclear, the
        selection is missing, or the verifier could not run.
    """
    if selection is None:
        return None

    from ci2lab.harness.multiagent.runner import run_subagent
    from ci2lab.harness.multiagent.state import AgentRole

    allow_execution = bool(config.auto_confirm)
    role = AgentRole.VALIDATOR if allow_execution else AgentRole.REVIEWER

    actions_text = "\n".join(f"- {a}" for a in actions) if actions else "- (none recorded)"
    task = _build_task(
        request=user_prompt,
        actions=actions_text,
        evidence=evidence_summary,
        previous_gaps=previous_gaps,
        allow_execution=allow_execution,
    )

    # Isolated token accounting; a fresh reviewer/validator subagent.
    parent_for_sub = replace(config, token_usage=TokenUsageState())
    result = run_subagent(
        role,
        task,
        selection,
        parent_for_sub,
        capture_output=True,
    )

    if result.status != "completed":
        # If the verifier itself could not run, do not block the user's task.
        return None

    verdict = parse_verdict(result.output)
    if verdict is not None:
        if verdict.is_actionable_failure:
            return _format_issues(verdict)
        return None

    # No structured verdict: fall back to the strict, conservative FAIL check.
    if _verdict_is_failure(result.output):
        return result.output.strip()
    return None
