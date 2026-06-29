"""Deterministic groundedness gate for the peer-review flow.

Reviewers do not emit free prose that we trust; they emit structured *findings*,
each carrying the evidence that backs it. This module parses those findings and
verifies each one against the manuscript index with plain Python — no model in
the loop. A finding only survives if:

* ``manuscript``  — its verbatim quote actually occurs in the manuscript;
* ``absence``     — every term it claims is missing is genuinely absent;
* ``external``    — its cited URL was actually fetched during this run.

Anything else is quarantined (kept out of the main review, surfaced in a
labelled appendix). This is the enforcement behind "the model must not invent or
hallucinate anything at all".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ci2lab.harness.multiagent.manuscript import (
    ManuscriptIndex,
    find_quote,
    term_present,
)

EVIDENCE_TYPES = frozenset({"manuscript", "absence", "external"})

# Disposition after verification.
#   verified      -> grounded; belongs in the review.
#   refuted       -> the manuscript contradicts the claim (model error, paper is
#                    fine); removed so the paper is not criticized unfairly.
#   needs_check   -> could NOT be verified due to a tool/model limit (paywall,
#                    dead link, no web, figure/equation not in extracted text,
#                    truncation). NOT a confirmed paper issue — verify manually.
#   quarantined   -> genuinely unsubstantiated (a quote that is simply not there
#                    with no innocent explanation); excluded, "do not send".
STATUS_VERIFIED = "verified"
STATUS_REFUTED = "refuted"
STATUS_NEEDS_CHECK = "needs_check"
STATUS_QUARANTINED = "quarantined"

# Words that signal a claim is about content text extraction usually drops
# (figures, tables, equations). An unfindable quote here is likely an extraction
# gap, not a hallucination, so it goes to "needs manual check", not quarantine.
_NON_TEXT_MARKERS = (
    "figure",
    "fig.",
    "fig ",
    "table",
    "equation",
    "eq.",
    "eq ",
    "formula",
    "chart",
    "plot",
    "diagram",
    "graph",
    "subfigure",
    "listing",
    "algorithm",
)


@dataclass
class Finding:
    """One reviewer claim plus the evidence required to verify it."""

    claim: str
    evidence_type: str
    lens: str = ""
    evidence_quote: str = ""
    anchor: str = ""
    absence_terms: list[str] = field(default_factory=list)
    external_url: str = ""
    severity: str = "minor"
    reviewer_judgment: str = ""
    # Filled in by verification:
    status: str = "pending"
    reason: str = ""
    category: str = ""  # machine tag for needs_check, e.g. "paywalled_or_login"
    matched_anchor: str | None = None

    def to_public(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of this finding's public fields."""
        return {
            "lens": self.lens,
            "claim": self.claim,
            "evidence_type": self.evidence_type,
            "evidence_quote": self.evidence_quote,
            "anchor": self.matched_anchor or self.anchor,
            "severity": self.severity,
            "reviewer_judgment": self.reviewer_judgment,
            "status": self.status,
            "reason": self.reason,
            "category": self.category,
        }


def _references_non_text(finding: Finding) -> bool:
    """True if the finding refers to a figure/table/equation (likely an extraction gap)."""
    haystack = f"{finding.claim} {finding.evidence_quote} {finding.reviewer_judgment}".lower()
    return any(marker in haystack for marker in _NON_TEXT_MARKERS)


@dataclass
class VerificationBuckets:
    """Findings grouped by disposition after deterministic verification."""

    verified: list[Finding] = field(default_factory=list)
    needs_check: list[Finding] = field(default_factory=list)
    refuted: list[Finding] = field(default_factory=list)
    quarantined: list[Finding] = field(default_factory=list)

    def merge(self, other: VerificationBuckets) -> None:
        """Extend each disposition list with the corresponding list from ``other``."""
        self.verified.extend(other.verified)
        self.needs_check.extend(other.needs_check)
        self.refuted.extend(other.refuted)
        self.quarantined.extend(other.quarantined)

    def add(self, finding: Finding) -> None:
        """Append ``finding`` to the bucket matching its status (quarantine by default)."""
        {
            STATUS_VERIFIED: self.verified,
            STATUS_NEEDS_CHECK: self.needs_check,
            STATUS_REFUTED: self.refuted,
            STATUS_QUARANTINED: self.quarantined,
        }.get(finding.status, self.quarantined).append(finding)


# --- parsing ---------------------------------------------------------------


def _as_list(value: Any) -> list[str]:
    """Coerce a string (split on ``;``/``,``) or sequence into a list of trimmed strings."""
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty value among ``keys`` in ``mapping`` (else ``""``)."""
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return ""


def _finding_from_dict(raw: dict[str, Any], *, default_lens: str = "") -> Finding | None:
    """Build a :class:`Finding` from a raw dict, inferring the evidence type if absent.

    Args:
        raw: A single parsed finding object from a reviewer's output.
        default_lens: Lens name to assign when the dict does not name one.

    Returns:
        The constructed :class:`Finding`, or ``None`` when it has no usable claim.
    """
    claim = str(_first(raw, "claim", "issue", "finding", "concern")).strip()
    if not claim:
        return None
    evidence_type = str(_first(raw, "evidence_type", "type", "kind")).strip().lower()
    if evidence_type not in EVIDENCE_TYPES:
        # Infer a sensible default: a quote => manuscript, a url => external.
        if _first(raw, "external_url", "url"):
            evidence_type = "external"
        elif _first(raw, "absence_terms", "terms", "missing_terms"):
            evidence_type = "absence"
        else:
            evidence_type = "manuscript"
    return Finding(
        claim=claim,
        evidence_type=evidence_type,
        lens=str(_first(raw, "lens") or default_lens),
        evidence_quote=str(_first(raw, "evidence_quote", "quote", "evidence")).strip(),
        anchor=str(_first(raw, "anchor", "ref", "location")).strip(),
        absence_terms=_as_list(_first(raw, "absence_terms", "terms", "missing_terms")),
        external_url=str(_first(raw, "external_url", "url", "source_url")).strip(),
        severity=(str(_first(raw, "severity", "priority")).strip().lower() or "minor"),
        reviewer_judgment=str(
            _first(raw, "reviewer_judgment", "judgment", "assessment", "comment")
        ).strip(),
    )


def _try_load(text: str) -> list[dict[str, Any]]:
    """Parse JSON and return its finding dicts, tolerating wrappers and single objects."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(data, dict):
        # Accept either a single finding or a wrapper like {"findings": [...]}.
        for key in ("findings", "items", "results"):
            if isinstance(data.get(key), list):
                return [item for item in data[key] if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _scan_objects(text: str) -> list[dict[str, Any]]:
    """Extract findings by scanning ``text`` for balanced top-level ``{...}`` objects."""
    objects: list[dict[str, Any]] = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    objects.extend(_try_load(text[start : i + 1]))
                    start = -1
    return objects


def parse_findings(text: str, *, default_lens: str = "") -> list[Finding]:
    """Best-effort extraction of structured findings from a reviewer's output.

    Weak local models rarely emit clean JSON, so we try fenced blocks, a bracket
    slice, a whole-text parse, and finally a balanced-brace object scan.
    """
    text = text or ""
    raw_dicts: list[dict[str, Any]] = []

    for block in re.findall(r"```(?:json)?\s*(.*?)```", text, re.S):
        raw_dicts.extend(_try_load(block.strip()))

    if not raw_dicts:
        raw_dicts.extend(_try_load(text.strip()))

    if not raw_dicts:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            raw_dicts.extend(_try_load(text[start : end + 1]))

    if not raw_dicts:
        raw_dicts.extend(_scan_objects(text))

    findings: list[Finding] = []
    for raw in raw_dicts:
        finding = _finding_from_dict(raw, default_lens=default_lens)
        if finding is not None:
            findings.append(finding)
    return findings


# --- external-reference evidence ------------------------------------------


def _normalize_url(url: str) -> str:
    """Normalize a URL for comparison: lowercased, fragment-stripped, no trailing slash."""
    url = str(url or "").strip().lower()
    url = re.sub(r"#.*$", "", url)
    url = re.sub(r"/+$", "", url)
    return url


def classify_fetch_failure(text: str) -> tuple[str, str]:
    """Map a failed web_fetch message to a (category, human reason).

    The category attributes the failure honestly: a paywall or dead link is not
    the paper's fault, so the cited reference may still be perfectly valid.
    """
    low = str(text or "").lower()
    if any(
        token in low
        for token in (
            "401",
            "403",
            "paywall",
            "subscribe",
            "subscription",
            "login",
            "sign in",
            "sign-in",
        )
    ):
        return (
            "paywalled_or_login",
            "Behind a paywall or login — could not read it. The citation may be valid; verify manually.",
        )
    if any(
        token in low
        for token in ("404", "410", "not found", "no such host", "name resolution", "dns")
    ):
        return (
            "dead_or_moved",
            "The link is dead or moved. The work may still exist under another URL/DOI; check it.",
        )
    if "429" in low or "rate limit" in low or "too many requests" in low:
        return "rate_limited", "The source rate-limited the fetch. Retry or verify manually."
    if any(token in low for token in ("robot", "captcha", "forbidden by", "blocked")):
        return "blocked", "The source blocked automated access. Verify manually."
    if any(
        token in low
        for token in (
            "timeout",
            "timed out",
            "connection",
            "network",
            "unreachable",
            "offline",
            "no internet",
        )
    ):
        return (
            "timeout_or_network",
            "Could not reach the source (timeout/offline). Not a paper issue; verify when online.",
        )
    return "fetch_failed", "Could not fetch the source. The citation may be valid; verify manually."


def extract_fetch_attempts(tool_calls: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Record every web_fetch attempt (success and failure) by normalized URL.

    Successes feed quote/citation verification; failures carry a category and
    reason so an unverifiable citation can be sent to manual review with an
    honest explanation instead of being condemned.
    """
    attempts: dict[str, dict[str, Any]] = {}
    for entry in tool_calls or []:
        if str(entry.get("tool") or "") != "web_fetch":
            continue
        args = entry.get("arguments") or {}
        url = args.get("url") if isinstance(args, dict) else None
        if not url:
            continue
        key = _normalize_url(str(url))
        if entry.get("ok", False):
            attempts[key] = {"ok": True, "category": "", "reason": ""}
            continue
        # Do not downgrade a prior success for the same URL.
        if attempts.get(key, {}).get("ok"):
            continue
        message = str(entry.get("error_preview") or entry.get("output_preview") or "")
        category, reason = classify_fetch_failure(message)
        attempts[key] = {"ok": False, "category": category, "reason": reason}
    return attempts


def extract_fetched_urls(tool_calls: list[dict[str, Any]]) -> set[str]:
    """Backward-compatible helper: the set of successfully fetched URLs."""
    return {url for url, info in extract_fetch_attempts(tool_calls).items() if info.get("ok")}


def _normalize_attempts(fetched: Any) -> dict[str, dict[str, Any]]:
    """Accept either a set of success URLs or a full attempts dict."""
    if isinstance(fetched, dict):
        return fetched
    return {
        _normalize_url(url): {"ok": True, "category": "", "reason": ""}
        for url in (fetched or set())
    }


# --- verification ----------------------------------------------------------


def verify_finding(
    finding: Finding,
    index: ManuscriptIndex,
    fetch_attempts: Any = None,
) -> Finding:
    """Verify one finding in place; set its disposition (status/category/reason).

    ``fetch_attempts`` may be a set of successfully fetched URLs or a dict of
    per-URL attempt info (see ``extract_fetch_attempts``).
    """
    attempts = _normalize_attempts(fetch_attempts)

    if finding.evidence_type == "manuscript":
        if not finding.evidence_quote:
            finding.status = STATUS_QUARANTINED
            finding.reason = "No verbatim quote supplied for a manuscript claim."
            return finding
        match = find_quote(index, finding.evidence_quote)
        if match.found:
            finding.status = STATUS_VERIFIED
            finding.matched_anchor = match.anchor
            if finding.anchor and match.anchor and _anchor_eq(finding.anchor, match.anchor):
                finding.reason = "Quote verified at the cited anchor."
            elif match.anchor:
                finding.reason = f"Quote verified; anchor corrected to {match.anchor}."
            else:
                finding.reason = "Quote verified in the manuscript."
        elif _references_non_text(finding):
            # Likely an extraction gap (figure/table/equation), not the paper's
            # fault — route to manual check rather than condemn it.
            finding.status = STATUS_NEEDS_CHECK
            finding.category = "non_text_content"
            finding.reason = (
                "Refers to a figure/table/equation that text extraction may not "
                "capture; verify against the original PDF."
            )
        else:
            finding.status = STATUS_QUARANTINED
            finding.reason = "Quoted text was not found in the manuscript."
        return finding

    if finding.evidence_type == "absence":
        if not finding.absence_terms:
            finding.status = STATUS_QUARANTINED
            finding.reason = "Absence claim has no searchable terms to confirm it."
            return finding
        present = [term for term in finding.absence_terms if term_present(index, term)]
        if present:
            # The model was wrong and the paper is fine: refute, don't criticize.
            finding.status = STATUS_REFUTED
            finding.reason = "Claimed missing, but the manuscript contains: " + ", ".join(
                sorted(set(present))
            )
        else:
            finding.status = STATUS_VERIFIED
            finding.reason = (
                "Confirmed absent: none of "
                + ", ".join(finding.absence_terms)
                + " appear in the manuscript."
            )
        return finding

    if finding.evidence_type == "external":
        key = _normalize_url(finding.external_url)
        info = attempts.get(key)
        if info and info.get("ok"):
            finding.status = STATUS_VERIFIED
            finding.reason = "External source was fetched and verified in this run."
        elif info:
            # Attempted but failed — attribute the reason honestly.
            finding.status = STATUS_NEEDS_CHECK
            finding.category = info.get("category") or "fetch_failed"
            finding.reason = info.get("reason") or "Could not fetch the source; verify manually."
        else:
            finding.status = STATUS_NEEDS_CHECK
            finding.category = "not_attempted"
            finding.reason = (
                "The cited source was not fetched in this run; verify the citation "
                "exists and supports the claim."
            )
        return finding

    finding.status = STATUS_QUARANTINED
    finding.reason = f"Unknown evidence type: {finding.evidence_type!r}."
    return finding


def _anchor_eq(a: str, b: str) -> bool:
    """True if two anchors share the same (non-empty) digit sequence."""
    norm = lambda s: re.sub(r"[^0-9]", "", str(s or ""))  # noqa: E731
    return norm(a) == norm(b) and norm(a) != ""


def verify_findings(
    findings: list[Finding],
    index: ManuscriptIndex,
    fetch_attempts: Any = None,
) -> VerificationBuckets:
    """Verify a batch and group findings by disposition."""
    buckets = VerificationBuckets()
    for finding in findings:
        verify_finding(finding, index, fetch_attempts)
        buckets.add(finding)
    return buckets


def regroundable(findings: list[Finding]) -> list[Finding]:
    """Quarantined findings worth one re-ground attempt.

    Only genuinely-quarantined manuscript/absence claims are re-grounded (the
    reviewer may supply an exact quote or precise terms). Findings sent to manual
    check (paywall, dead link, figures) or refuted by the manuscript cannot be
    salvaged by re-grounding, so they are excluded.
    """
    return [
        finding
        for finding in findings
        if finding.status == STATUS_QUARANTINED
        and finding.evidence_type in {"manuscript", "absence"}
    ]
