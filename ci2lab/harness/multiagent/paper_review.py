"""Grounded scientific peer-review flow: context, prompts, and report assembly.

This module holds the *pure* parts of the peer-review pipeline — the review
context, the prompt builders for each grounded lens, and the assembly of the
final report (verified findings + a quarantine appendix + a coverage note). The
orchestration that actually runs the subagents and threads the deterministic
verification between them lives in ``orchestrator.py`` (which imports from here).

Keeping these pieces pure keeps the most important behavior — that the report is
built only from verified, anchored findings — unit-testable without a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ci2lab.harness.multiagent.grounding import Finding
from ci2lab.harness.multiagent.manuscript import ManuscriptIndex


@dataclass
class ReviewContext:
    """Everything a grounded review of one manuscript needs."""

    index: ManuscriptIndex
    paper_meta: dict[str, Any] = field(default_factory=dict)
    reviewer_block: str = ""
    manuscript_source_name: str = ""
    # url -> {"ok": bool, "category": str, "reason": str} (see grounding.py).
    fetch_attempts: dict[str, Any] = field(default_factory=dict)

    @property
    def readable(self) -> bool:
        """Whether the underlying manuscript index is readable for review."""
        return self.index.readable

    @property
    def fetched_ok(self) -> int:
        """Number of external sources that were successfully fetched this run."""
        return sum(1 for info in self.fetch_attempts.values() if info.get("ok"))


REFUSAL_MESSAGE = (
    "PAPER REVIEW NOT POSSIBLE\n\n"
    "I could not read a manuscript to review. A grounded peer review must be based "
    "only on the actual paper, so I will not produce a review from the title, the "
    "abstract, or prior knowledge.\n\n"
    "To proceed, add the manuscript (PDF, DOCX, MD, or TXT) as a source in this "
    "paper-review project and run the review again."
)


def _meta_block(ctx: ReviewContext) -> str:
    """Render the ``<review_brief>`` block from the context's paper metadata."""
    meta = ctx.paper_meta or {}
    rows = [
        ("Title", meta.get("paper_title")),
        ("Field", meta.get("field")),
        ("Target venue", meta.get("target_venue")),
        ("Article type", meta.get("article_type")),
    ]
    lines = [f"- {label}: {value}" for label, value in rows if value]
    if not lines:
        lines = ["- (No field/venue/type provided — infer them and mark as inferred.)"]
    return "<review_brief>\n" + "\n".join(lines) + "\n</review_brief>"


def _manuscript_block(ctx: ReviewContext, *, text: str | None = None, part_label: str = "") -> str:
    """Render the ``<manuscript>`` block of anchored text shown to a reviewer."""
    body = text if text is not None else ctx.index.anchored_text
    header = (
        "The paper, segmented with [A#] anchors. Cite these anchors and quote "
        "verbatim from here — this is the only source of truth about the paper."
    )
    if part_label:
        header += (
            f" You are reviewing {part_label} of the manuscript; cite only the "
            "anchors shown here and do not infer content from sections you cannot see."
        )
    return f"<manuscript>\n{header}\n\n{body}\n</manuscript>"


def _base_prompt(
    ctx: ReviewContext,
    *,
    task: str,
    extra: str = "",
    chunk_text: str | None = None,
    part_label: str = "",
) -> str:
    """Assemble a reviewer prompt with task, brief, manuscript, and output contract."""
    parts = [task.strip(), _meta_block(ctx)]
    if ctx.reviewer_block:
        parts.append(ctx.reviewer_block)
    if extra:
        parts.append(extra.strip())
    parts.append(_manuscript_block(ctx, text=chunk_text, part_label=part_label))
    parts.append(
        "Return your findings as a JSON array following the grounding contract. "
        "Add a short prose summary before the JSON if helpful, but every claim "
        "about the paper must appear as a finding with a verbatim quote + anchor "
        "(or an absence with search terms, or an external_url you fetched)."
    )
    return "\n\n".join(parts)


def _findings_prompt(ctx: ReviewContext, *, task: str, extra: str = "") -> str:
    """A reduce-stage prompt with NO manuscript block.

    The planner/groundedness verifier work on findings (which already carry their
    own quotes and anchors), so the full manuscript must not be re-injected — that
    is what would overflow the window on a long paper.
    """
    parts = [task.strip(), _meta_block(ctx)]
    if ctx.reviewer_block:
        parts.append(ctx.reviewer_block)
    if extra:
        parts.append(extra.strip())
    return "\n\n".join(parts)


def build_intake_prompt(
    ctx: ReviewContext, *, chunk_text: str | None = None, part_label: str = ""
) -> str:
    """Build the intake/diagnosis reviewer prompt for ``ctx`` (or one chunk of it)."""
    return _base_prompt(
        ctx,
        chunk_text=chunk_text,
        part_label=part_label,
        task=(
            "Diagnose this manuscript before detailed review. Provide: a faithful "
            "5-7 line summary; the field/subfield, target venue, and article type "
            "(use the brief, else infer and mark as inferred); the manuscript "
            "maturity (engineering_report | early_manuscript | submission_candidate "
            "| near_ready) with a one-line reason; an EVIDENCE AUDIT listing which "
            "of {baselines, metrics, ablations, failure cases, reproducibility "
            "package, comparison with prior work} are present vs absent; and the "
            "single claimed main contribution. Back presence claims with quotes and "
            "absence claims with the exact terms you searched."
        ),
    )


_LENS_TASKS: dict[str, str] = {
    "scope_reviewer": (
        "Assess whether the manuscript fits the target venue and its editorial "
        "expectations. Give fit (High/Medium/Low), desk-rejection risk (Low/Medium/"
        "High), the main reason, and concrete changes to improve fit."
    ),
    "novelty_reviewer": (
        "Audit the contribution. Separate the CLAIMED contribution from the ACTUAL, "
        "supported one; flag any claim that exceeds the evidence; judge whether this "
        "is an engineering artifact or a research contribution; and state what must "
        "be added to make the contribution defensible. Only cite external prior work "
        "you actually fetched."
    ),
    "methodology_reviewer": (
        "Evaluate methodological soundness and reproducibility: justified design "
        "decisions, metrics, baselines, comparisons, ablations, threats to validity, "
        "and reported limitations. Tie each weakness to a concrete missing experiment."
    ),
    "field_expert_reviewer": (
        "Raise the concerns this paper's specific field/community would require, each "
        "with a concrete fix. Adapt to the reviewer profile's field if given."
    ),
    "adversarial_reviewer": (
        "As a tough Reviewer 2, build the strongest good-faith case to REJECT this "
        "manuscript at the target venue, ranked by severity, then state exactly what "
        "must change to move to accept. Do not invent flaws."
    ),
    "format_reviewer": (
        "Produce a submission-readiness checklist for the target venue: length, "
        "sections, abstract, keywords, references, figures/tables, data availability, "
        "code availability, ethics/AI-use statement, conflicts, author contributions. "
        "Mark each PASS/FAIL/UNKNOWN with the fix needed."
    ),
}


def build_lens_prompt(
    lens_value: str,
    ctx: ReviewContext,
    intake_text: str,
    *,
    chunk_text: str | None = None,
    part_label: str = "",
) -> str:
    """Build a lens reviewer's prompt, folding the intake diagnosis in as context.

    Args:
        lens_value: The lens role value selecting which task text to use.
        ctx: The review context for this manuscript.
        intake_text: Shared intake diagnosis to attach as re-verifiable context.
        chunk_text: Optional anchored text for a single chunk of the manuscript.
        part_label: Optional label naming the chunk (e.g. ``"part 2 of 3"``).

    Returns:
        The assembled reviewer prompt string.
    """
    task = _LENS_TASKS.get(lens_value, "Review the manuscript within your role.")
    extra = ""
    if intake_text.strip():
        extra = (
            "<intake_diagnosis>\n"
            "Shared diagnosis from the intake reviewer (context only — re-verify "
            "anything you rely on against the manuscript):\n"
            f"{intake_text.strip()[:6000]}\n</intake_diagnosis>"
        )
    return _base_prompt(ctx, task=task, extra=extra, chunk_text=chunk_text, part_label=part_label)


def build_reground_prompt(
    ctx: ReviewContext,
    failed: list[Finding],
    *,
    chunk_text: str | None = None,
    part_label: str = "",
) -> str:
    """Build a prompt asking a reviewer to re-ground its unverified findings.

    Args:
        ctx: The review context for this manuscript.
        failed: The findings that failed deterministic verification.
        chunk_text: Optional anchored text for a single chunk of the manuscript.
        part_label: Optional label naming the chunk being reviewed.

    Returns:
        The assembled re-grounding prompt string.
    """
    lines = []
    for i, finding in enumerate(failed, start=1):
        lines.append(
            f"{i}. claim: {finding.claim}\n"
            f"   why it failed: {finding.reason}\n"
            f"   evidence_type: {finding.evidence_type}"
        )
    failed_block = "<unverified_findings>\n" + "\n".join(lines) + "\n</unverified_findings>"
    task = (
        "Your previous findings below could NOT be verified against the manuscript. "
        "For each one you still believe is correct, RE-GROUND it: supply the exact "
        "verbatim quote and its [A#] anchor from the manuscript (for a manuscript "
        "claim), or the precise terms you searched (for an absence claim). If you "
        "cannot ground it in the manuscript, DROP it — do not restate it. Return "
        "only the re-grounded findings as a JSON array."
    )
    return _base_prompt(
        ctx, task=task, extra=failed_block, chunk_text=chunk_text, part_label=part_label
    )


def build_groundedness_prompt(ctx: ReviewContext, verified: list[Finding]) -> str:
    """Build the verifier prompt asking whether each quote actually supports its claim."""
    lines = []
    for i, finding in enumerate(verified):
        lines.append(
            f"[{i}] claim: {finding.claim}\n"
            f'    quote: "{finding.evidence_quote}"\n'
            f"    anchor: {finding.matched_anchor or finding.anchor}"
        )
    block = "<findings_to_check>\n" + "\n".join(lines) + "\n</findings_to_check>"
    task = (
        "Each finding below has a quote already confirmed to exist in the "
        "manuscript. Check the harder question: does the quote ACTUALLY support the "
        "claim, or is the claim an over-reading or misattribution? Return a JSON "
        'array of {"index": <number>, "supported": true|false, "reason": '
        '"..."}. Default to supported=false when the quote does not clearly back '
        "the claim."
    )
    return _findings_prompt(ctx, task=task, extra=block)


def build_revision_plan_prompt(ctx: ReviewContext, verified: list[Finding]) -> str:
    """Build the revision-planner prompt that synthesizes verified findings into a report."""
    findings_block = "<verified_findings>\n" + format_findings(verified) + "\n</verified_findings>"
    task = (
        "Synthesize ONLY the verified findings below into a decision-ready report. "
        "Do not add any finding or claim that is not in the list, and keep each "
        "supporting [A#] anchor. Use EXACTLY this structure:\n\n"
        "PAPER REVIEW REPORT\n"
        "1. Summary\n"
        "2. Journal Fit (fit /10, desk-rejection risk, main reason)\n"
        "3. Contribution Assessment (claimed, actual, novelty risk, how to strengthen)\n"
        "4. Methodological Review (strengths, weaknesses, missing evidence, suggested experiments)\n"
        "5. Field-Specific Concerns\n"
        "6. Reviewer 2 Critique (major criticisms; what must change to accept)\n"
        "7. Formatting & Submission Checklist\n"
        "8. Manuscript Maturity (engineering_report | early_manuscript | submission_candidate | near_ready)\n"
        "9. Required Changes Before Submission (Priority 1/2/3)\n"
        "10. Verdict (Acceptable now? No/Almost/Yes; recommended action: accept | "
        "minor revision | major revision | reject | not-a-paper-yet)\n\n"
        "Adapt tone/emphasis to the reviewer profile and the field/venue, but keep "
        "the structure stable so reviews are comparable across versions."
    )
    return _findings_prompt(ctx, task=task, extra=findings_block)


# --- report assembly -------------------------------------------------------


_LENS_LABELS = {
    "intake_reviewer": "Intake / diagnosis",
    "scope_reviewer": "Journal fit",
    "novelty_reviewer": "Contribution & novelty",
    "methodology_reviewer": "Methodology & evidence",
    "field_expert_reviewer": "Field-specific",
    "adversarial_reviewer": "Reviewer 2",
    "format_reviewer": "Formatting & submission",
}


def format_findings(findings: list[Finding]) -> str:
    """Render findings as a human-readable, anchored bullet list (``"(none)"`` if empty)."""
    if not findings:
        return "(none)"
    lines = []
    for finding in findings:
        anchor = finding.matched_anchor or finding.anchor or "?"
        label = _LENS_LABELS.get(finding.lens, finding.lens or "review")
        header = f"- [{label}] ({finding.severity}) {finding.claim}"
        if finding.evidence_type == "manuscript" and finding.evidence_quote:
            header += f'\n  Evidence [{anchor}]: "{finding.evidence_quote}"'
        elif finding.evidence_type == "absence":
            header += f"\n  Evidence: confirmed absent ({', '.join(finding.absence_terms)})"
        elif finding.evidence_type == "external" and finding.external_url:
            header += f"\n  Evidence (fetched): {finding.external_url}"
        if finding.reviewer_judgment:
            header += f"\n  Reviewer note: {finding.reviewer_judgment}"
        lines.append(header)
    return "\n".join(lines)


# Human-friendly headings for the "needs manual check" categories.
_CATEGORY_LABELS = {
    "paywalled_or_login": "Reference behind a paywall / login",
    "dead_or_moved": "Reference link dead or moved",
    "timeout_or_network": "Reference unreachable (timeout/offline)",
    "rate_limited": "Reference fetch rate-limited",
    "blocked": "Reference blocked automated access",
    "fetch_failed": "Reference could not be fetched",
    "not_attempted": "Reference not checked in this run",
    "non_text_content": "Claim about a figure/table/equation",
    "coverage_truncated": "Section not reviewed (length limit)",
}


def _format_needs_check(findings: list[Finding], *, truncated: bool) -> str:
    """Render the 'could not verify' findings (plus a truncation note) as a bullet list."""
    lines: list[str] = []
    if truncated:
        lines.append(
            "- [Coverage] The manuscript exceeded the model's input budget, so its "
            "later sections were not reviewed. This is a tool limit, not a paper "
            "issue — review the remaining sections manually."
        )
    for finding in findings:
        label = _CATEGORY_LABELS.get(finding.category, finding.category or "Unverifiable")
        line = f"- [{label}] {finding.claim}"
        if finding.evidence_type == "external" and finding.external_url:
            line += f"\n  Source: {finding.external_url}"
        line += f"\n  Why unverified: {finding.reason}"
        lines.append(line)
    return "\n".join(lines) if lines else "(none)"


def _coverage_note(
    ctx: ReviewContext,
    *,
    verified_count: int,
    needs_check_count: int,
    refuted_count: int,
    quarantined_count: int,
) -> str:
    """Render the coverage & limitations section summarizing what was reviewed."""
    index = ctx.index
    parts = [
        f"- Manuscript source: {ctx.manuscript_source_name or 'unknown'}",
        f"- Segments indexed: {index.segment_count} "
        f"(shown to reviewers: {index.shown_segment_count})",
    ]
    if index.truncated:
        parts.append(
            "- WARNING: the manuscript exceeded the prompt budget; later sections "
            "were not reviewed (see 'Could not verify')."
        )
    parts.append(f"- External sources fetched and verified: {ctx.fetched_ok}")
    parts.append(
        f"- Findings: {verified_count} verified, {needs_check_count} need a manual "
        f"check (tool limits, not paper issues), {refuted_count} auto-filtered to "
        f"avoid unfair criticism, {quarantined_count} unsubstantiated and dropped."
    )
    return "## Coverage & limitations\n" + "\n".join(parts)


def assemble_report(
    ctx: ReviewContext,
    planner_output: str,
    verified: list[Finding],
    needs_check: list[Finding],
    refuted: list[Finding],
    quarantined: list[Finding],
) -> str:
    """Assemble the final review with honest, attributed appendices.

    The body and grounded findings hold only verified claims. Separate sections
    distinguish what we could NOT verify because of our own limits (paywalls,
    dead links, figures, truncation) from what the manuscript actually refutes
    and from genuinely unsubstantiated claims — so the paper is never blamed for
    the tool's blind spots.
    """
    body = planner_output.strip() if planner_output and planner_output.strip() else ""
    if not body:
        body = "PAPER REVIEW REPORT (assembled from verified findings)\n\n" + format_findings(
            verified
        )

    sections = [body]
    sections.append(
        "## Grounded findings (verified against the manuscript)\n" + format_findings(verified)
    )

    if needs_check or ctx.index.truncated:
        sections.append(
            "## Could not verify — please check manually (NOT confirmed paper issues)\n"
            "These could not be checked due to limits of this tool (no/blocked web "
            "access, paywalls, dead links, figures/equations not in the extracted "
            "text, or length limits). They are not confirmed problems with the "
            "paper; a human should verify each — a valid reference behind a paywall "
            "is still a valid reference.\n"
            + _format_needs_check(needs_check, truncated=ctx.index.truncated)
        )

    if refuted:
        r_lines = []
        for finding in refuted:
            label = _LENS_LABELS.get(finding.lens, finding.lens or "review")
            r_lines.append(f"- [{label}] {finding.claim}\n  Removed because: {finding.reason}")
        sections.append(
            "## Auto-filtered to avoid unfair criticism\n"
            "A reviewer raised these, but the manuscript actually addresses them, so "
            "they were removed from the review:\n" + "\n".join(r_lines)
        )

    if quarantined:
        q_lines = []
        for finding in quarantined:
            label = _LENS_LABELS.get(finding.lens, finding.lens or "review")
            q_lines.append(f"- [{label}] {finding.claim}\n  Dropped because: {finding.reason}")
        sections.append(
            "## Unsubstantiated — DO NOT send to authors\n"
            "These could not be grounded in the manuscript and have no innocent "
            "explanation, so they are excluded from the review above:\n" + "\n".join(q_lines)
        )

    sections.append(
        _coverage_note(
            ctx,
            verified_count=len(verified),
            needs_check_count=len(needs_check) + (1 if ctx.index.truncated else 0),
            refuted_count=len(refuted),
            quarantined_count=len(quarantined),
        )
    )
    return "\n\n".join(sections)


# --- output quality gate ---------------------------------------------------
#
# Never ship a rubbish review. After the run, if the model clearly could not do
# the job (ignored the structured contract, fabricated most quotes, or produced
# nothing usable), we drop the result and recommend a stronger/larger model.

# Fraction of reviewer calls that must at least attempt structured output.
MIN_STRUCTURED_RATE = 0.25
# Above this many manuscript findings, check the fabrication rate.
HALLUCINATION_MIN_FINDINGS = 4
# If this fraction of manuscript quotes are not in the paper, the model fabricates.
MAX_HALLUCINATION_RATE = 0.6


@dataclass
class QualitySignals:
    """Accumulated signals about how well the model actually performed."""

    lens_runs: int = 0
    structured_runs: int = 0
    manuscript_findings: int = 0
    hallucinated: int = 0
    verified: int = 0
    needs_check: int = 0
    refuted: int = 0
    planner_report_ok: bool = False

    def note_lens_run(self, raw_output: str) -> None:
        """Record one lens run, counting it as structured if it attempted the contract."""
        self.lens_runs += 1
        if looks_structured(raw_output):
            self.structured_runs += 1

    @property
    def structured_rate(self) -> float:
        """Fraction of lens runs that attempted structured output (0.0 if none ran)."""
        return self.structured_runs / self.lens_runs if self.lens_runs else 0.0


def looks_structured(text: str) -> bool:
    """Did the output even attempt the required JSON-array contract?"""
    text = text or ""
    if "```" in text and "json" in text.lower():
        return True
    return ("[" in text and "]" in text) or ("{" in text and "}" in text)


def assess_quality(signals: QualitySignals) -> tuple[bool, str]:
    """Return ``(ok, reason)``; ``ok=False`` means the result is not trustworthy."""
    if signals.lens_runs and signals.structured_rate < MIN_STRUCTURED_RATE:
        return False, (
            "The model rarely produced the required structured output, so its "
            "responses could not be turned into a grounded review."
        )
    if signals.manuscript_findings >= HALLUCINATION_MIN_FINDINGS:
        rate = signals.hallucinated / signals.manuscript_findings
        if rate >= MAX_HALLUCINATION_RATE:
            return False, (
                "Most of the model's quotes could not be found in the manuscript "
                "(fabricated), so its review cannot be trusted."
            )
    total_useful = signals.verified + signals.needs_check + signals.refuted
    if total_useful == 0 and not signals.planner_report_ok and signals.structured_rate < 0.5:
        return False, "The model did not produce any usable, grounded review content."
    return True, ""


def quality_abort_message(
    reason: str,
    *,
    model_name: str,
    recommended_min_context: int = 0,
) -> str:
    """Build the abort message shown when the review result would not be reliable.

    Args:
        reason: Human-readable explanation of why the result was rejected.
        model_name: The model that produced the unreliable result.
        recommended_min_context: Suggested minimum context window in tokens; when
            non-zero it is woven into the recommendation.

    Returns:
        The formatted abort message.
    """
    extra = ""
    if recommended_min_context:
        extra = f" with at least ~{recommended_min_context} tokens of context"
    return (
        "PAPER REVIEW STOPPED — THE RESULT WOULD NOT BE RELIABLE\n\n"
        f"{reason}\n\n"
        "This usually means the model is too small or weak for a grounded review "
        "of this manuscript. Rather than return a misleading review, it was "
        "stopped.\n\n"
        f"Current model: {model_name or 'unknown'}. Install a stronger/larger "
        f"model{extra} (run `ci2lab models recommend`) and try again."
    )
