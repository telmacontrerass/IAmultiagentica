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
TRANSCRIBE_DOCUMENT_SKILL = "transcribe_document"

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

# Audit/solve intent: the user wants the calculations *checked*, not just read.
# Bare "transcribe"/"handwritten" no longer lives here — that is transcription.
_EXERCISE_REVIEW_RE = re.compile(
    r"(?:"
    r"check\b.{0,40}\b(?:calc|calcul|result|answer|work)|"
    r"verify\b.{0,40}\b(?:calc|calcul|result|answer|work)|"
    r"step\s*by\s*step|"
    r"which\b.{0,30}\bwrong|"
    r"find\b.{0,20}\b(?:error|mistake)|"
    r"audit\b.{0,30}\b(?:exercise|work|solution)|"
    r"correct\b.{0,30}\b(?:exercise|exam|solution|work)|"
    r"is\b.{0,20}\bcorrect|"
    # Spanish audit/solve verbs (matched verbatim per project convention).
    r"corrig|corríge|revisa\b.{0,30}\b(?:cálculo|calculo|resultado)|"
    r"está\b.{0,15}\b(?:bien|mal)|resuélve|resuelve"
    r")",
    re.IGNORECASE | re.DOTALL,
)

# Transcription intent: the user wants the document read out / passed to clean
# text, with no judgement of correctness.
_TRANSCRIPTION_RE = re.compile(
    r"(?:"
    r"transcri|"  # transcribe / transcription / transcribir / transcripción
    r"handwrit|handwritten|scanned|"
    r"pasa(?:r)?\s+a\s+limpio|"  # ES: "pasar a limpio"
    r"manuscrito|escaneado|"  # ES: handwritten / scanned
    r"(?:convert|pass|turn)\b.{0,25}\b(?:to\s+text|plain\s+text)|"
    r"read\b.{0,25}\bhandwrit|"
    r"what\b.{0,15}\b(?:does|says?)\b.{0,25}\bsay"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def is_exercise_review_request(text: str) -> bool:
    """Return True when the user wants the work's calculations checked/audited.

    Args:
        text: The user's request text to match against the intent regex.

    Returns:
        ``True`` if the text matches the exercise-review (audit/solve) intent.
    """
    return bool(_EXERCISE_REVIEW_RE.search(text or ""))


def is_transcription_request(text: str) -> bool:
    """Return True when the user wants a plain transcription (no checking).

    Args:
        text: The user's request text to match against the intent regex.

    Returns:
        ``True`` if the text matches the transcription intent.
    """
    return bool(_TRANSCRIPTION_RE.search(text or ""))


def select_visual_skill(text: str) -> str | None:
    """Pick which visual-document skill a prompt should trigger.

    Audit/solve intent takes precedence over plain transcription so a prompt
    like "transcribe and check each step" still runs the full review.

    Args:
        text: The user's request text.

    Returns:
        ``REVIEW_HANDWRITTEN_EXERCISE_SKILL``, ``TRANSCRIBE_DOCUMENT_SKILL``,
        or ``None`` when neither intent matches.
    """
    if is_exercise_review_request(text):
        return REVIEW_HANDWRITTEN_EXERCISE_SKILL
    if is_transcription_request(text):
        return TRANSCRIBE_DOCUMENT_SKILL
    return None


def is_visual_document_request(text: str) -> bool:
    """Return True for any transcription- or review-style visual-document turn.

    Used to gate sharp PDF rendering and the literal transcription prompt, which
    both apply whether the user wants a plain transcription or a full audit.
    """
    return select_visual_skill(text) is not None


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
    cwd: str,
    user_args: str = "",
    skill_name: str = REVIEW_HANDWRITTEN_EXERCISE_SKILL,
) -> tuple[str, frozenset[str] | None] | None:
    """Return skill instructions to prepend to the user turn, or None if missing.

    Args:
        cwd: Working directory used to discover and load skills.
        user_args: Optional user arguments rendered into the skill header.
        skill_name: Which builtin visual-document skill to load.

    Returns:
        A ``(prefix_text, allowed_tools)`` tuple, where ``allowed_tools`` is
        the skill's allowed-tool set or ``None`` if unrestricted; or ``None``
        if the skill is not found.
    """
    skills = load_skills(cwd)
    skill = get_skill(skills, skill_name)
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
    skill_name = select_visual_skill(user_prompt)
    if skill_name is None:
        return None
    prefix = build_exercise_skill_prefix(cwd, user_args=user_prompt, skill_name=skill_name)
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
    skill_name = select_visual_skill(user_prompt)
    if skill_name is None:
        return content, None

    prefix = build_exercise_skill_prefix(cwd, user_args=user_prompt, skill_name=skill_name)
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
