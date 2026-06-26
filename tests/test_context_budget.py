"""Tests for context budgeting and plan-divide-conquer chunk planning."""

from ci2lab.harness.multiagent import context_budget as cb
from ci2lab.harness.multiagent import manuscript


def _long_index(paragraphs: int = 12, words: int = 120):
    body = "\n\n".join(
        f"Section {i}. " + ("alpha beta gamma delta epsilon zeta " * (words // 6))
        for i in range(paragraphs)
    )
    return manuscript.build_index(body)


def test_budget_grows_with_context_window():
    small = cb.manuscript_budget(8192)[0]
    big = cb.manuscript_budget(32768)[0]
    assert big > small > 0


def test_tiny_context_is_infeasible_and_recommends_bigger():
    index = _long_index()
    feas = cb.assess_feasibility(index, 2048)
    assert feas.feasible is False
    assert feas.recommended_min_context >= 8192
    assert "context window is too small" in feas.reason.lower()


def test_normal_context_is_feasible_single_or_few_chunks():
    index = manuscript.build_index("A short manuscript. " * 50)
    feas = cb.assess_feasibility(index, 8192)
    assert feas.feasible is True
    assert feas.n_chunks >= 1


def test_long_manuscript_splits_into_multiple_chunks():
    index = _long_index(paragraphs=16, words=200)
    budget = cb.manuscript_budget(8192)[0]
    chunks = cb.plan_chunks(index.segments, budget)
    assert len(chunks) > 1
    # Every chunk stays within budget (a lone oversized segment is the only
    # allowed exception, and our segments are capped below the budget).
    for chunk in chunks:
        if len(chunk) > 1:
            assert len(cb.chunk_anchored_text(chunk)) <= budget
    # No segment is lost in the split.
    assert sum(len(c) for c in chunks) == len(index.segments)


def test_too_many_chunks_is_infeasible():
    # A large manuscript on a small (but per-chunk-feasible) window needs more
    # than MAX_CHUNKS chunks -> recommend a bigger model rather than fragment.
    index = _long_index(paragraphs=40, words=200)
    feas = cb.assess_feasibility(index, 4096)
    assert feas.feasible is False
    assert "chunks" in feas.reason.lower()
    assert feas.recommended_min_context >= 8192


def test_recommended_context_uses_standard_tiers():
    assert cb.recommended_context_for(10_000) in cb.STANDARD_TIERS
    assert cb.recommended_context_for(5_000_000) == cb.STANDARD_TIERS[-1]


def test_infeasible_message_points_to_recommend():
    index = _long_index()
    feas = cb.assess_feasibility(index, 2048)
    msg = cb.infeasible_message(feas, model_name="tiny:1b", context_length=2048)
    assert "NOT POSSIBLE" in msg
    assert "models recommend" in msg
    assert "tiny:1b" in msg
