"""Tests for the focused vision-transcription clean-up pass."""

from unittest.mock import patch

from ci2lab.harness import default_selection
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.vision_exercise import clean_transcription

RAW = (
    "## page_001.png\n\n"
    "C8H18 + 12.5(O2 + 3.76N2) -> 8CO2 + 9H2O + 47N2\n"
    "Tca = To + [hcomb] / [8CpCO2 + 9CpH2O + n7CpN2]"
)


def _selection():
    return default_selection("test:1b")


def test_clean_transcription_returns_corrected_text():
    corrected = RAW.replace("n7CpN2", "47CpN2")
    with patch("ci2lab.harness.llm_client.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = LLMResponse(content=corrected, tool_calls=[])
        result = clean_transcription(RAW, _selection())

    assert result == corrected
    assert "n7CpN2" not in result


def test_clean_transcription_strips_preamble_free_but_keeps_structure():
    # The model is asked to output only the transcription; a clean corrected
    # answer of similar length passes the guard unchanged.
    corrected = RAW.replace("n7", "47")
    with patch("ci2lab.harness.llm_client.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = LLMResponse(content=corrected, tool_calls=[])
        assert clean_transcription(RAW, _selection()) == corrected


def test_audit_shaped_answer_falls_back_to_raw():
    audit = (
        "## Audit\n| Step | Seen | Affects Result |\n"
        "The student's final answer for part b was incorrect."
    )
    with patch("ci2lab.harness.llm_client.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = LLMResponse(content=audit, tool_calls=[])
        assert clean_transcription(RAW, _selection()) == RAW


def test_length_blowout_falls_back_to_raw():
    padded = RAW + "\n\n" + ("extra commentary line\n" * 200)
    with patch("ci2lab.harness.llm_client.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = LLMResponse(content=padded, tool_calls=[])
        assert clean_transcription(RAW, _selection()) == RAW


def test_empty_model_answer_falls_back_to_raw():
    with patch("ci2lab.harness.llm_client.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = LLMResponse(content="", tool_calls=[])
        assert clean_transcription(RAW, _selection()) == RAW


def test_model_error_falls_back_to_raw():
    with patch("ci2lab.harness.llm_client.LLMClient") as MockClient:
        MockClient.return_value.chat.side_effect = RuntimeError("backend down")
        assert clean_transcription(RAW, _selection()) == RAW


def test_blank_input_returned_unchanged_without_model_call():
    with patch("ci2lab.harness.llm_client.LLMClient") as MockClient:
        assert clean_transcription("   ", _selection()) == "   "
        MockClient.return_value.chat.assert_not_called()
