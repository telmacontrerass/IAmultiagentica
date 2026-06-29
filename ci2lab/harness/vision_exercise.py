"""Handwritten exercise review: intent detection, transcription prompts, skill wiring.

Used when a user asks to transcribe and verify handwritten or scanned work.
Qwen (vision_model) extracts literal text; the main model follows the
``review_handwritten_exercise`` builtin skill to classify errors and rework
problems when they affect the final answer.
"""

from __future__ import annotations

import re
from typing import Any

from ci2lab.harness.skills.loader import get_skill, load_skills

REVIEW_HANDWRITTEN_EXERCISE_SKILL = "review_handwritten_exercise"

EXERCISE_TRANSCRIPTION_PROMPT = (
    "Transcribe every visible item on this page literally. Include:\n"
    "- All equations, chemical formulas, and reaction arrows\n"
    "- Every number, unit, subscript, and superscript (write subscripts inline, e.g. C8H18)\n"
    "- Step labels (1, 2, a, b) and handwritten annotations\n"
    "- Tables and boxed final answers\n\n"
    "Rules:\n"
    "- Copy what you see; do NOT judge whether calculations are correct\n"
    "- If a digit or symbol is ambiguous, show both readings in brackets "
    "(e.g. [4.7 or 47?])\n"
    "- Mark illegible spans as [illegible]\n"
    "- Preserve line breaks between steps"
)

_EXERCISE_REVIEW_RE = re.compile(
    r"(?:"
    r"transcri|handwrit|handwritten|scanned|"
    r"check\b.{0,40}\b(?:calc|calcul|result|answer|work)|"
    r"verify\b.{0,40}\b(?:calc|calcul|result|answer|work)|"
    r"step\s*by\s*step|"
    r"which\b.{0,30}\bwrong|"
    r"find\b.{0,20}\b(?:error|mistake)|"
    r"audit\b.{0,30}\b(?:exercise|work|solution)"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def is_exercise_review_request(text: str) -> bool:
    """Return True when the user wants transcription plus calculation checking.

    Args:
        text: The user's request text to match against the intent regex.

    Returns:
        ``True`` if the text matches the exercise-review intent pattern.
    """
    return bool(_EXERCISE_REVIEW_RE.search(text or ""))


def should_apply_exercise_review_skill(user_prompt: str, *, has_vision_input: bool) -> bool:
    """Whether to auto-load the handwritten exercise review skill.

    Args:
        user_prompt: The user's request text.
        has_vision_input: Whether the turn includes image/PDF input.

    Returns:
        ``True`` only when there is vision input and the prompt matches the
        exercise-review intent.
    """
    if not has_vision_input:
        return False
    return is_exercise_review_request(user_prompt)


def build_exercise_skill_prefix(
    cwd: str, user_args: str = ""
) -> tuple[str, frozenset[str] | None] | None:
    """Return skill instructions to prepend to the user turn, or None if missing.

    Args:
        cwd: Working directory used to discover and load skills.
        user_args: Optional user arguments rendered into the skill header.

    Returns:
        A ``(prefix_text, allowed_tools)`` tuple, where ``allowed_tools`` is
        the skill's allowed-tool set or ``None`` if unrestricted; or ``None``
        if the skill is not found.
    """
    skills = load_skills(cwd)
    skill = get_skill(skills, REVIEW_HANDWRITTEN_EXERCISE_SKILL)
    if skill is None:
        return None

    allowed = frozenset(skill.allowed_tools) if skill.allowed_tools else None
    header = f"# Skill: {skill.name}\n\n{skill.description}\n"
    if user_args.strip():
        header += f"\n**User arguments:** {user_args.strip()}\n"
    if skill.allowed_tools:
        header += (
            "\n**Allowed tools for this skill:** "
            + ", ".join(f"`{t}`" for t in skill.allowed_tools)
            + "\n"
        )
    return f"{header}\n{skill.body}", allowed


def enrich_user_prompt_with_exercise_skill(
    user_prompt: str,
    cwd: str,
) -> tuple[str, frozenset[str] | None] | None:
    """Prepend the exercise review skill body to a plain-text user prompt.

    Args:
        user_prompt: The plain-text user prompt to enrich.
        cwd: Working directory used to load the skill.

    Returns:
        A ``(enriched_prompt, allowed_tools)`` tuple, or ``None`` if the skill
        should not be applied or could not be loaded.
    """
    if not should_apply_exercise_review_skill(user_prompt, has_vision_input=True):
        return None
    prefix = build_exercise_skill_prefix(cwd, user_args=user_prompt)
    if prefix is None:
        return None
    body, allowed = prefix
    enriched = f"{body}\n\n---\nUser request: {user_prompt.strip()}"
    return enriched, allowed


def enrich_turn_content_with_exercise_skill(
    user_prompt: str,
    content: str | list[dict[str, Any]],
    cwd: str,
) -> tuple[str | list[dict[str, Any]], frozenset[str] | None]:
    """Prepend skill instructions to user content (text or multimodal list).

    Args:
        user_prompt: The user's request text (used for intent detection).
        content: The turn content, either a plain string or an OpenAI-style
            multipart list of blocks.
        cwd: Working directory used to load the skill.

    Returns:
        A ``(content, allowed_tools)`` tuple. When the skill applies, the
        instructions are prepended to ``content`` (in-place on a copy for
        lists); otherwise the original content is returned with ``None``.
    """
    if not should_apply_exercise_review_skill(user_prompt, has_vision_input=True):
        return content, None

    prefix = build_exercise_skill_prefix(cwd, user_args=user_prompt)
    if prefix is None:
        return content, None
    body, allowed = prefix
    skill_block = (
        f"{body}\n\n---\n"
        "Follow this skill workflow for the attached visual document(s).\n"
        f"User request: {user_prompt.strip()}"
    )

    if isinstance(content, list):
        new_content = [dict(block) for block in content]
        if new_content and new_content[0].get("type") == "text":
            new_content[0]["text"] = skill_block + "\n\n" + (new_content[0].get("text") or "")
        else:
            new_content.insert(0, {"type": "text", "text": skill_block})
        return new_content, allowed

    return skill_block + "\n\n" + content, allowed
