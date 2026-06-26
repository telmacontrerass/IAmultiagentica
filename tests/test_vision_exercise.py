"""Tests for handwritten exercise review helpers and builtin skill."""

from __future__ import annotations

from ci2lab.harness.skills.loader import load_skills
from ci2lab.harness.tools.skill_tool import invoke_skill
from ci2lab.harness.types import AgentConfig
from ci2lab.harness.vision_exercise import (
    REVIEW_HANDWRITTEN_EXERCISE_SKILL,
    enrich_turn_content_with_exercise_skill,
    is_exercise_review_request,
    should_apply_exercise_review_skill,
)


def test_is_exercise_review_request_matches_transcribe_and_check():
    prompt = (
        "Transcribe the handwritten work in P1_T1_IE.pdf, then check each "
        "calculation and final result step by step and tell me which are wrong."
    )
    assert is_exercise_review_request(prompt) is True


def test_is_exercise_review_request_rejects_unrelated():
    assert is_exercise_review_request("List the Python files in this repo") is False


def test_should_apply_exercise_review_skill_requires_vision_input():
    prompt = "Transcribe and check calculations step by step"
    assert should_apply_exercise_review_skill(prompt, has_vision_input=False) is False
    assert should_apply_exercise_review_skill(prompt, has_vision_input=True) is True


def test_builtin_review_handwritten_exercise_skill_available():
    skills = load_skills(".")
    assert REVIEW_HANDWRITTEN_EXERCISE_SKILL in skills
    skill = skills[REVIEW_HANDWRITTEN_EXERCISE_SKILL]
    assert skill.source == "builtin"
    assert skill.allowed_tools == ["todo_write", "extract_visual_document"]


def test_invoke_review_handwritten_exercise_skill_contract():
    cfg = AgentConfig(cwd=".")
    prompt = invoke_skill(cfg, REVIEW_HANDWRITTEN_EXERCISE_SKILL, "P1_T1_IE.pdf")
    assert cfg.skill_allowed_tools == frozenset({"todo_write", "extract_visual_document"})
    assert "Audit" in prompt
    assert "affects_result" in prompt
    assert "Corrected solution" in prompt
    assert "extract_visual_document" in prompt


def test_enrich_turn_content_with_exercise_skill_prepends_text():
    user_prompt = "Transcribe P1_T1_IE.pdf and check each calculation step by step."
    content = user_prompt + "\n\n[Image: page_001.png]\nC8H18 + ..."
    enriched, allowed = enrich_turn_content_with_exercise_skill(
        user_prompt,
        content,
        ".",
    )
    assert isinstance(enriched, str)
    assert enriched.startswith("# Skill: review_handwritten_exercise")
    assert "User request:" in enriched
    assert allowed == frozenset({"todo_write", "extract_visual_document"})


def test_enrich_turn_content_with_exercise_skill_multimodal():
    user_prompt = "Check handwritten calculations step by step in the attached pages."
    content = [
        {"type": "text", "text": user_prompt},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]
    enriched, allowed = enrich_turn_content_with_exercise_skill(
        user_prompt,
        content,
        ".",
    )
    assert allowed is not None
    assert enriched[0]["type"] == "text"
    assert enriched[0]["text"].startswith("# Skill: review_handwritten_exercise")
    assert enriched[1]["type"] == "image_url"


def test_enrich_turn_content_skips_unrelated_prompt():
    content = "Summarize this image."
    enriched, allowed = enrich_turn_content_with_exercise_skill(
        "Summarize this image.",
        content,
        ".",
    )
    assert enriched == content
    assert allowed is None
