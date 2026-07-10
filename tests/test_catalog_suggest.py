"""Tests for suggest_similar_models — the catalog "did you mean" helper."""

from __future__ import annotations

from ci2lab.router.catalog import suggest_similar_models


def test_typo_suggests_the_correct_tag() -> None:
    # A missing letter in a real tag should surface the intended model.
    suggestions = suggest_similar_models("qwen2.5-codr:7b")
    assert "qwen2.5-coder:7b" in suggestions


def test_blank_input_returns_no_suggestions() -> None:
    assert suggest_similar_models("   ") == []


def test_unrelated_name_returns_no_suggestions() -> None:
    # A genuine custom model that resembles nothing must not be second-guessed.
    assert suggest_similar_models("zzzzzzzzzzzzz") == []


def test_limit_is_respected() -> None:
    assert len(suggest_similar_models("qwen2.5-coder:7b", limit=1)) == 1


def test_suggestions_are_deduplicated_by_tag() -> None:
    # Matching both a model's id and its ollama_tag must collapse to one tag.
    suggestions = suggest_similar_models("qwen2.5-coder:7b")
    assert len(suggestions) == len(set(suggestions))
