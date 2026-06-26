"""Make the model's context window a non-problem for grounded review.

A local model has a finite context window. A manuscript plus the reviewer's
instructions, reasoning, and output can easily exceed it — and an overflowed
context silently drops text, which for a review means an *incomplete* (i.e.
wrong) result. We refuse to ship that.

The strategy here is plan-divide-conquer / context-packing:

1. Compute, from the model's real context window, how much manuscript text can
   safely go into ONE reviewer call (reserving room for the prompt and the
   model's output, and using only a conservative fraction of the window because
   quality degrades well before the nominal limit — "lost in the middle").
2. Divide the manuscript into chunks that each fit that budget, keeping segments
   (and their anchors) whole.
3. Each reviewer call sees only one chunk, so the window is never exceeded; the
   manuscript is reviewed across several iterations and the findings are merged.
4. If even one usable chunk will not fit, or the paper would need too many
   chunks to review well, we do NOT try anyway — we abort and recommend a
   larger-context model. Producing rubbish is never acceptable.

Pure module (no model calls, no I/O) so the budgeting is fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from ci2lab.harness.multiagent.manuscript import ManuscriptIndex, Segment

# Token<->char estimate. ~4 chars/token for English; we use a slightly lower
# value so token counts are over-estimated and char budgets under-estimated —
# i.e. we err toward NOT overflowing.
CHARS_PER_TOKEN = 3.5

# Only this fraction of the window is treated as reliably usable. Effective
# context is well below the advertised size (context rot / lost-in-the-middle),
# and model confusion grows superlinearly with input length, so we stay well
# under the limit on purpose.
USABLE_FRACTION = 0.6

# Tokens reserved for the model's own generated findings (kept out of the input
# budget so output is never truncated).
OUTPUT_RESERVE_TOKENS = 1200

# Rough tokens consumed by the fixed parts of a reviewer prompt (base system
# prompt, role instructions, grounding contract, review brief, reviewer profile).
# Conservative; tune if reviewer prompts grow.
FIXED_OVERHEAD_TOKENS = 1200

# A chunk must hold at least this much manuscript to be a meaningful reviewable
# unit. Below this, the model is too small — recommend a larger one.
MIN_MANUSCRIPT_CHUNK_TOKENS = 500

# More chunks than this means too much fragmentation / aggregator noise for a
# trustworthy review — recommend a larger-context model instead.
MAX_CHUNKS = 12

# When recommending a model, aim to fit the manuscript in at most this many
# comfortable chunks.
RECOMMEND_TARGET_CHUNKS = 6

# Standard context tiers to recommend (tokens).
STANDARD_TIERS = (8192, 16384, 32768, 65536, 131072)


def estimate_tokens(text: str) -> int:
    return int(len(text or "") / CHARS_PER_TOKEN)


def _seg_block(segment: Segment) -> str:
    return f"[{segment.anchor}] {segment.display}"


def manuscript_budget(context_length: int) -> tuple[int, int]:
    """Return ``(budget_chars, manuscript_tokens)`` for one reviewer call."""
    context_length = max(0, int(context_length or 0))
    input_tokens = context_length - OUTPUT_RESERVE_TOKENS
    quality_tokens = input_tokens * USABLE_FRACTION
    manuscript_tokens = int(quality_tokens - FIXED_OVERHEAD_TOKENS)
    if manuscript_tokens <= 0:
        return 0, manuscript_tokens
    return int(manuscript_tokens * CHARS_PER_TOKEN), manuscript_tokens


def plan_chunks(segments, budget_chars: int) -> list[list[Segment]]:
    """Greedily pack whole segments into chunks no larger than ``budget_chars``."""
    chunks: list[list[Segment]] = []
    current: list[Segment] = []
    used = 0
    for segment in segments:
        block_len = len(_seg_block(segment)) + 2
        if current and used + block_len > budget_chars:
            chunks.append(current)
            current = []
            used = 0
        current.append(segment)
        used += block_len
    if current:
        chunks.append(current)
    return chunks


def chunk_anchored_text(segments: list[Segment]) -> str:
    return "\n\n".join(_seg_block(segment) for segment in segments)


def total_manuscript_chars(index: ManuscriptIndex) -> int:
    return sum(len(_seg_block(segment)) + 2 for segment in index.segments)


def recommended_context_for(total_chars: int) -> int:
    """Smallest standard context tier that would review the paper comfortably."""
    needed_per_chunk_chars = max(1, total_chars / RECOMMEND_TARGET_CHUNKS)
    needed_manuscript_tokens = needed_per_chunk_chars / CHARS_PER_TOKEN
    needed_context = (
        (needed_manuscript_tokens + FIXED_OVERHEAD_TOKENS) / USABLE_FRACTION
        + OUTPUT_RESERVE_TOKENS
    )
    for tier in STANDARD_TIERS:
        if tier >= needed_context:
            return tier
    return STANDARD_TIERS[-1]


@dataclass(frozen=True)
class Feasibility:
    """Whether the current model can review this manuscript well."""

    feasible: bool
    n_chunks: int
    budget_chars: int
    manuscript_tokens: int
    reason: str
    recommended_min_context: int  # tokens; 0 when feasible


def assess_feasibility(index: ManuscriptIndex, context_length: int) -> Feasibility:
    """Decide whether to review (and in how many chunks) or recommend a bigger model."""
    budget_chars, manuscript_tokens = manuscript_budget(context_length)
    total_chars = total_manuscript_chars(index)

    if manuscript_tokens < MIN_MANUSCRIPT_CHUNK_TOKENS or budget_chars <= 0:
        return Feasibility(
            feasible=False,
            n_chunks=0,
            budget_chars=budget_chars,
            manuscript_tokens=manuscript_tokens,
            reason=(
                "The model's context window is too small to review even one "
                "section of the manuscript reliably."
            ),
            recommended_min_context=recommended_context_for(total_chars),
        )

    chunks = plan_chunks(index.segments, budget_chars)
    n_chunks = len(chunks)
    if n_chunks > MAX_CHUNKS:
        return Feasibility(
            feasible=False,
            n_chunks=n_chunks,
            budget_chars=budget_chars,
            manuscript_tokens=manuscript_tokens,
            reason=(
                f"The manuscript would need {n_chunks} chunks at this context size "
                f"(max {MAX_CHUNKS}); that is too fragmented for a trustworthy review."
            ),
            recommended_min_context=recommended_context_for(total_chars),
        )

    return Feasibility(
        feasible=True,
        n_chunks=n_chunks,
        budget_chars=budget_chars,
        manuscript_tokens=manuscript_tokens,
        reason=(
            f"Manuscript fits in {n_chunks} chunk(s) within the model's usable context."
        ),
        recommended_min_context=0,
    )


def infeasible_message(
    feasibility: Feasibility,
    *,
    model_name: str,
    context_length: int,
) -> str:
    """A clear abort message recommending a larger-context model."""
    need = feasibility.recommended_min_context
    return (
        "PAPER REVIEW NOT POSSIBLE WITH THIS MODEL\n\n"
        f"{feasibility.reason}\n\n"
        f"Current model: {model_name or 'unknown'} (~{context_length} token context).\n"
        f"Recommended: a model with at least ~{need} tokens of context.\n\n"
        "A grounded review must read the whole manuscript; rather than skip "
        "sections and risk an incomplete review, install a larger-context model "
        "(run `ci2lab models recommend`) and try again."
    )
