"""Tests for the peer-review groundedness substrate.

These are the anti-hallucination guarantees: a real quote must verify, an
invented one must be rejected, a false 'missing X' claim must be refuted, and an
unfetched external citation must be quarantined.
"""

from ci2lab.harness.multiagent import grounding, manuscript
from ci2lab.harness.multiagent.grounding import Finding

MANUSCRIPT = """\
Title: A Local Multi-Agent Harness for Reproducible Review

Abstract. We present CI2Lab, a local agent harness that runs open-source models
on consumer hardware. The system enforces per-phase permissions and logs every
tool call for traceability.

Methodology. We evaluate the harness on three coding tasks and report the
success rate. No baseline comparison against existing agent frameworks is
included in this version of the manuscript.

Results. The harness completed two of the three tasks. We discuss failure cases
in the appendix.
"""


def _index():
    return manuscript.build_index(MANUSCRIPT)


# --- indexing --------------------------------------------------------------


def test_build_index_assigns_sequential_anchors():
    index = _index()
    assert index.readable
    assert index.segment_count >= 4
    assert index.segments[0].anchor == "A1"
    assert all(seg.anchor.startswith("A") for seg in index.segments)
    assert "[A1]" in index.anchored_text


def test_anchored_text_can_be_truncated_but_segments_are_complete():
    index = manuscript.build_index(MANUSCRIPT, anchored_char_budget=120)
    assert index.truncated is True
    assert index.shown_segment_count < index.segment_count
    # Verification still has every segment even though the prompt was capped.
    assert index.segment_count >= 4


# --- quote verification ----------------------------------------------------


def test_exact_quote_is_found_with_anchor():
    index = _index()
    match = manuscript.find_quote(index, "enforces per-phase permissions and logs every tool call")
    assert match.found is True
    assert match.anchor is not None
    assert match.exact is True


def test_quote_match_tolerates_case_punctuation_and_accents():
    index = _index()
    match = manuscript.find_quote(index, "We Present CI2Lab, a LOCAL agent harness!!!")
    assert match.found is True


def test_invented_quote_is_rejected():
    index = _index()
    match = manuscript.find_quote(
        index, "the system achieves state-of-the-art results on every benchmark"
    )
    assert match.found is False


def test_too_short_quote_is_not_verifiable():
    index = _index()
    assert manuscript.find_quote(index, "the").found is False


def test_term_present_detects_real_and_missing_terms():
    index = _index()
    assert manuscript.term_present(index, "success rate") is True
    assert manuscript.term_present(index, "Monte Carlo simulation") is False


# --- finding parsing -------------------------------------------------------


def test_parse_findings_from_fenced_json_array():
    text = """Here are my findings:
```json
[{"claim": "No baseline", "evidence_type": "absence", "absence_terms": ["baseline"]}]
```
"""
    findings = grounding.parse_findings(text)
    assert len(findings) == 1
    assert findings[0].evidence_type == "absence"
    assert findings[0].absence_terms == ["baseline"]


def test_parse_findings_tolerates_key_aliases_and_wrapper():
    text = (
        '{"findings": [{"issue": "Overclaim", "type": "manuscript", "quote": "state of the art"}]}'
    )
    findings = grounding.parse_findings(text)
    assert len(findings) == 1
    assert findings[0].claim == "Overclaim"
    assert findings[0].evidence_type == "manuscript"
    assert findings[0].evidence_quote == "state of the art"


def test_parse_findings_scans_loose_objects():
    text = 'noise {"claim": "x", "type": "manuscript", "quote": "logs every tool call"} trailing'
    findings = grounding.parse_findings(text)
    assert len(findings) == 1
    assert findings[0].claim == "x"


# --- verification gate -----------------------------------------------------


def test_manuscript_finding_with_real_quote_is_verified():
    index = _index()
    finding = Finding(
        claim="The system logs tool calls.",
        evidence_type="manuscript",
        evidence_quote="logs every tool call for traceability",
        anchor="A2",
    )
    grounding.verify_finding(finding, index, set())
    assert finding.status == "verified"
    assert finding.matched_anchor is not None


def test_manuscript_finding_with_invented_quote_is_quarantined():
    index = _index()
    finding = Finding(
        claim="The paper claims SOTA.",
        evidence_type="manuscript",
        evidence_quote="we beat all prior systems by a wide margin",
    )
    grounding.verify_finding(finding, index, set())
    assert finding.status == "quarantined"


def test_absence_finding_is_verified_when_terms_truly_missing():
    index = _index()
    finding = Finding(
        claim="No statistical significance test is reported.",
        evidence_type="absence",
        absence_terms=["p-value", "statistical significance"],
    )
    grounding.verify_finding(finding, index, set())
    assert finding.status == "verified"


def test_false_absence_finding_is_refuted_not_blamed_on_paper():
    index = _index()
    finding = Finding(
        claim="No baseline is reported.",
        evidence_type="absence",
        absence_terms=["baseline comparison"],
    )
    grounding.verify_finding(finding, index, set())
    # The manuscript mentions a baseline comparison: the model was wrong and the
    # paper is fine, so this is refuted (auto-filtered), not blamed on the paper.
    assert finding.status == "refuted"


def test_manuscript_claim_about_a_figure_goes_to_manual_check():
    index = _index()
    finding = Finding(
        claim="Figure 3 shows the architecture is overly complex.",
        evidence_type="manuscript",
        evidence_quote="the architecture diagram in figure 3 has twelve modules",
    )
    grounding.verify_finding(finding, index, set())
    # Text extraction drops figures, so an unfindable figure quote is a tool
    # limit, not a hallucination — route it to manual check.
    assert finding.status == "needs_check"
    assert finding.category == "non_text_content"


def test_absence_finding_without_terms_is_quarantined():
    index = _index()
    finding = Finding(claim="Something is missing.", evidence_type="absence")
    grounding.verify_finding(finding, index, set())
    assert finding.status == "quarantined"


def test_fetched_external_is_verified_unfetched_goes_to_manual_check():
    index = _index()
    attempts = {"https://arxiv.org/abs/1234.5678": {"ok": True, "category": "", "reason": ""}}
    ok = Finding(
        claim="Similar to prior work.",
        evidence_type="external",
        external_url="https://arxiv.org/abs/1234.5678/",
    )
    unfetched = Finding(
        claim="Similar to prior work.",
        evidence_type="external",
        external_url="https://example.com/never-fetched",
    )
    grounding.verify_finding(ok, index, attempts)
    grounding.verify_finding(unfetched, index, attempts)
    assert ok.status == "verified"
    # An unverifiable citation is sent to manual check, never condemned.
    assert unfetched.status == "needs_check"
    assert unfetched.category == "not_attempted"


def test_paywalled_reference_is_attributed_not_blamed():
    index = _index()
    attempts = {
        "https://journal.example/article": {
            "ok": False,
            "category": "paywalled_or_login",
            "reason": "Behind a paywall.",
        }
    }
    finding = Finding(
        claim="Builds on prior method X.",
        evidence_type="external",
        external_url="https://journal.example/article",
    )
    grounding.verify_finding(finding, index, attempts)
    assert finding.status == "needs_check"
    assert finding.category == "paywalled_or_login"


def test_classify_fetch_failure_categories():
    assert grounding.classify_fetch_failure("HTTP 403 Forbidden")[0] == "paywalled_or_login"
    assert grounding.classify_fetch_failure("404 Not Found")[0] == "dead_or_moved"
    assert grounding.classify_fetch_failure("connection timed out")[0] == "timeout_or_network"
    assert grounding.classify_fetch_failure("429 Too Many Requests")[0] == "rate_limited"


def test_extract_fetch_attempts_records_success_and_failure():
    tool_calls = [
        {"tool": "web_fetch", "ok": True, "arguments": {"url": "https://A.com/"}},
        {
            "tool": "web_fetch",
            "ok": False,
            "arguments": {"url": "https://B.com"},
            "error_preview": "403 paywall",
        },
        {"tool": "web_search", "ok": True, "arguments": {"query": "C"}},
    ]
    attempts = grounding.extract_fetch_attempts(tool_calls)
    assert attempts["https://a.com"]["ok"] is True
    assert attempts["https://b.com"]["ok"] is False
    assert attempts["https://b.com"]["category"] == "paywalled_or_login"
    # Backward-compatible helper still returns just the successes.
    assert grounding.extract_fetched_urls(tool_calls) == {"https://a.com"}


def test_verify_findings_groups_by_disposition():
    index = _index()
    findings = [
        Finding(claim="real", evidence_type="manuscript", evidence_quote="logs every tool call"),
        Finding(
            claim="fake", evidence_type="manuscript", evidence_quote="invented nonsense span here"
        ),
        Finding(claim="ext", evidence_type="external", external_url="https://nope.example"),
        Finding(claim="false-absence", evidence_type="absence", absence_terms=["success rate"]),
    ]
    buckets = grounding.verify_findings(findings, index, set())
    assert [f.claim for f in buckets.verified] == ["real"]
    assert [f.claim for f in buckets.quarantined] == ["fake"]
    assert [f.claim for f in buckets.needs_check] == ["ext"]
    assert [f.claim for f in buckets.refuted] == ["false-absence"]
    # Only the genuinely-unsubstantiated manuscript claim is re-groundable.
    regroundable = grounding.regroundable(buckets.quarantined)
    assert len(regroundable) == 1
    assert regroundable[0].claim == "fake"
