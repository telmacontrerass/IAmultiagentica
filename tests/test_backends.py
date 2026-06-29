"""Tests for the pluggable LLM backend layer and the provider config seam."""

from __future__ import annotations

from unittest.mock import patch

from ci2lab.config import load_config
from ci2lab.contracts import HardwareProfile
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.backends import (
    OllamaBackend,
    OpenAICompatBackend,
    create_backend,
)
from ci2lab.router.selection import build_model_selection


def _profile() -> HardwareProfile:
    return HardwareProfile(
        ram_total_gb=32.0,
        ram_available_gb=16.0,
        vram_total_gb=8.0,
        vram_available_gb=7.0,
        gpu_name="Test GPU",
        gpu_vendor="nvidia",
        cpu_cores=8,
        os="linux",
        inference_mode="gpu",
        inference_budget_gb=5.5,
        inference_budget_theoretical_gb=6.0,
        inference_budget_available_gb=5.5,
        memory_pressure=False,
    )


def _selection(**overrides) -> ModelSelection:
    base = dict(model_id="m", ollama_tag="m:tag", display_name="M")
    base.update(overrides)
    return ModelSelection(**base)


def test_create_backend_selects_ollama():
    backend = create_backend(_selection(backend="ollama", backend_url="http://localhost:11434/v1"))
    assert isinstance(backend, OllamaBackend)
    # The native endpoint sits at the server root, not under /v1.
    assert backend.chat_url == "http://localhost:11434/api/chat"


def test_create_backend_selects_openai():
    backend = create_backend(_selection(backend="openai", backend_url="http://vllm:8000/v1"))
    assert isinstance(backend, OpenAICompatBackend)
    assert backend.chat_url == "http://vllm:8000/v1/chat/completions"


def test_create_backend_unknown_provider_falls_back_to_openai():
    backend = create_backend(_selection(backend="lmstudio", backend_url="http://x:1/v1"))
    assert isinstance(backend, OpenAICompatBackend)


@patch("ci2lab.router.selection.scan_hardware", return_value=_profile())
def test_build_model_selection_records_provider(_mock_scan):
    ollama = build_model_selection("qwen2.5-coder:7b", backend="ollama")
    openai = build_model_selection("qwen2.5-coder:7b", backend="openai")
    assert ollama.backend == "ollama"
    assert openai.backend == "openai"


def test_config_reads_backend_from_env(monkeypatch):
    monkeypatch.setenv("CI2LAB_BACKEND", "openai")
    config = load_config()
    assert config.backend == "openai"


def test_config_backend_defaults_to_ollama(monkeypatch):
    monkeypatch.delenv("CI2LAB_BACKEND", raising=False)
    config = load_config()
    assert config.backend == "ollama"
