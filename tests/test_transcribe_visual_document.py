"""Tests for the vision-only transcription path (vision read + reasoning proofread)."""

from unittest.mock import patch

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.vision_exercise import _strip_wrapping_fence, transcribe_visual_document


def test_reads_with_vision_then_proofreads_with_reasoning_model():
    cfg = AgentConfig(cwd=".", vision_model="qwen2.5vl:7b")
    selection = default_selection("test:1b")

    with (
        patch(
            "ci2lab.harness.vision.analyze_image",
            return_value="```markdown\nTca = J989,92 K\n```",
        ) as mock_vision,
        # Proofread is a distinct reasoning-model call; stub it to a fixed fix so
        # the test asserts the wiring, not the model.
        patch(
            "ci2lab.harness.vision_exercise.clean_transcription",
            side_effect=lambda raw, selection: raw.replace("J989", "5989"),
        ) as mock_proof,
    ):
        result = transcribe_visual_document(["page.png"], selection, cfg)

    mock_vision.assert_called_once()
    mock_proof.assert_called_once()
    assert "## page.png" in result
    assert "Tca = 5989,92 K" in result  # proofread fix applied
    assert "```" not in result  # wrapping fence stripped before proofread


def test_no_vision_model_returns_note_without_calling_anything():
    cfg = AgentConfig(cwd=".", vision_model="")
    selection = default_selection("test:1b")

    with (
        patch("ci2lab.harness.vision.analyze_image") as mock_vision,
        patch("ci2lab.harness.vision_exercise.clean_transcription") as mock_proof,
    ):
        result = transcribe_visual_document(["page.png"], selection, cfg)

    mock_vision.assert_not_called()
    mock_proof.assert_not_called()
    assert "modelo de visión" in result


def test_vision_disabled_returns_note():
    cfg = AgentConfig(cwd=".", vision_model="qwen2.5vl:7b", vision_enabled=False)
    selection = default_selection("test:1b")

    with patch("ci2lab.harness.vision_exercise.clean_transcription") as mock_proof:
        result = transcribe_visual_document(["p.png"], selection, cfg)

    mock_proof.assert_not_called()
    assert "visión está desactivada" in result


def test_strip_wrapping_fence():
    assert _strip_wrapping_fence("```markdown\nA\nB\n```") == "A\nB"
    assert _strip_wrapping_fence("A\nB\n") == "A\nB"
    inner = "Intro\n```\ncode\n```\nOutro"
    assert _strip_wrapping_fence(inner) == inner
