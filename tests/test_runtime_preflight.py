"""Tests for check_model_available — the pre-flight model-availability gate."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ci2lab.contracts.types import ModelSelection
from ci2lab.runtime.preflight import ModelUnavailableError, check_model_available


def _selection(**overrides: object) -> ModelSelection:
    fields: dict[str, object] = {
        "model_id": "qwen2.5-coder-7b",
        "ollama_tag": "qwen2.5-coder:7b",
        "display_name": "Qwen2.5 Coder 7B",
    }
    fields.update(overrides)
    return ModelSelection(**fields)  # type: ignore[arg-type]


def test_non_ollama_backend_is_a_noop() -> None:
    # An OpenAI-compatible server provisions models remotely: do not probe Ollama.
    selection = _selection(backend="openai", backend_url="http://localhost:1234/v1")
    with patch("ci2lab.runtime.preflight.fetch_installed_model_names") as fetch:
        check_model_available(selection)
    fetch.assert_not_called()


def test_installed_model_passes() -> None:
    selection = _selection()
    with patch(
        "ci2lab.runtime.preflight.fetch_installed_model_names",
        return_value=({"qwen2.5-coder:7b"}, None),
    ):
        check_model_available(selection)  # does not raise


def test_unreachable_ollama_raises_with_serve_hint() -> None:
    selection = _selection()
    with patch(
        "ci2lab.runtime.preflight.fetch_installed_model_names",
        return_value=(set(), "Connection refused"),
    ):
        with pytest.raises(ModelUnavailableError, match="not responding"):
            check_model_available(selection)


def test_known_model_not_installed_has_no_did_you_mean() -> None:
    # A real catalog model that just is not pulled is not a typo.
    selection = _selection()
    with patch(
        "ci2lab.runtime.preflight.fetch_installed_model_names",
        return_value=(set(), None),
    ):
        with pytest.raises(ModelUnavailableError) as exc_info:
            check_model_available(selection)
    message = str(exc_info.value)
    assert "not installed" in message
    assert "Did you mean" not in message
    assert "ollama pull qwen2.5-coder:7b" in message


def test_mistyped_tag_suggests_the_correct_one() -> None:
    selection = _selection(model_id="qwen2.5-codr-7b", ollama_tag="qwen2.5-codr:7b")
    with patch(
        "ci2lab.runtime.preflight.fetch_installed_model_names",
        return_value=(set(), None),
    ):
        with pytest.raises(ModelUnavailableError) as exc_info:
            check_model_available(selection)
    message = str(exc_info.value)
    assert "Did you mean" in message
    assert "qwen2.5-coder:7b" in message


def test_unknown_custom_model_has_no_spurious_suggestion() -> None:
    selection = _selection(model_id="my-custom", ollama_tag="my-custom-model:latest")
    with patch(
        "ci2lab.runtime.preflight.fetch_installed_model_names",
        return_value=(set(), None),
    ):
        with pytest.raises(ModelUnavailableError) as exc_info:
            check_model_available(selection)
    message = str(exc_info.value)
    assert "not installed" in message
    assert "Did you mean" not in message
