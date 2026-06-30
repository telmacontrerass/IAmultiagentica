"""Final-answer review entry point."""

from __future__ import annotations

from dataclasses import dataclass

from ci2lab.harness.grounding_review.evidence import EvidenceLedger
from ci2lab.harness.grounding_review.rules import find_grounding_issues

FINAL_ANSWER_REVIEW_MAX_PER_TURN = 2


@dataclass(frozen=True)
class ReviewResult:
    """Result of the deterministic final-answer groundedness gate."""

    ok: bool
    issues: tuple[str, ...] = ()
    instruction: str = ""


def review_final_answer(answer: str, ledger: EvidenceLedger) -> ReviewResult:
    """Check whether a final answer is grounded in this turn's evidence."""
    issues = tuple(find_grounding_issues(answer, ledger))
    if not issues:
        return ReviewResult(ok=True)

    bullets = "\n".join(f"- {issue}" for issue in issues)
    instruction = (
        "Default groundedness review blocked the draft final answer because it "
        "contains claims that are not supported by the evidence collected this turn.\n\n"
        "Blocked issues:\n"
        f"{bullets}\n\n"
        "Evidence available this turn:\n"
        f"{ledger.summary()}\n\n"
        "Do not invent missing facts. Use the appropriate read-only tool "
        "(`read_file`, `grep`, `git_status`, `bash` for checks, or `web_search`/`web_fetch` "
        "for current external facts) to verify the claims, then answer from that evidence. "
        "If tools are unavailable, the user asked not to use them, or verification is not "
        "possible, revise the answer to clearly say what cannot be confirmed."
    )
    return ReviewResult(ok=False, issues=issues, instruction=instruction)


def guarded_uncertain_answer(review: ReviewResult) -> str:
    """Fallback final text when unsupported claims remain after review attempts."""
    if review.ok:
        return ""
    bullets = "\n".join(f"- {issue}" for issue in review.issues)
    return (
        "I cannot safely confirm the drafted answer from the evidence available in this turn.\n\n"
        "Unverified claim(s):\n"
        f"{bullets}\n\n"
        "I will not present those claims as fact without verification."
    )
