"""Tests for the vision-only transcription path (no reasoning model)."""

from unittest.mock import patch

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.vision_exercise import _strip_wrapping_fence, transcribe_visual_document


def test_assembles_vision_reads_and_strips_fence():
    cfg = AgentConfig(cwd=".", vision_model="qwen2.5vl:7b")
    selection = default_selection("test:1b")

    with patch(
        "ci2lab.harness.vision.analyze_image",
        return_value="```markdown\nProblema 1\nx = 2\n```",
    ) as mock_vision:
        result = transcribe_visual_document(["page.png"], selection, cfg)

    # The reasoning model is never involved — only the vision model is called.
    mock_vision.assert_called_once()
    assert "## page.png" in result
    assert "Problema 1" in result
    assert "```" not in result  # wrapping fence stripped


def test_no_vision_model_returns_note_without_calling_vision():
    cfg = AgentConfig(cwd=".", vision_model="")
    selection = default_selection("test:1b")

    with patch("ci2lab.harness.vision.analyze_image") as mock_vision:
        result = transcribe_visual_document(["page.png"], selection, cfg)

    mock_vision.assert_not_called()
    assert "modelo de visión" in result


def test_vision_disabled_returns_note():
    cfg = AgentConfig(cwd=".", vision_model="qwen2.5vl:7b", vision_enabled=False)
    selection = default_selection("test:1b")

    assert "visión está desactivada" in transcribe_visual_document(["p.png"], selection, cfg)


def test_strip_wrapping_fence():
    assert _strip_wrapping_fence("```markdown\nA\nB\n```") == "A\nB"
    assert _strip_wrapping_fence("A\nB\n") == "A\nB"
    inner = "Intro\n```\ncode\n```\nOutro"
    assert _strip_wrapping_fence(inner) == inner
