"""
Tests del contador de tokens: captura desde Ollama → LLMResponse → loop → RunLogger.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_client import LLMClient, LLMResponse, StreamToken
from ci2lab.harness.run_logger import RunLogger
from ci2lab.harness.types import AgentConfig


# ---------------------------------------------------------------------------
# Fixture compartida
# ---------------------------------------------------------------------------

def _selection() -> ModelSelection:
    return ModelSelection(
        model_id="qwen2.5-coder-7b",
        ollama_tag="qwen2.5-coder:7b",
        display_name="Qwen2.5 Coder 7B",
        context_length=32768,
    )


# ---------------------------------------------------------------------------
# 1. LLMClient.chat() captura usage
# ---------------------------------------------------------------------------

class _FakeChatClient:
    """Mock httpx.Client para modo no-streaming con usage en la respuesta."""

    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json):
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Cuatro"}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 3, "total_tokens": 45},
            },
            request=request,
        )


def test_chat_captura_usage(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _FakeChatClient)
    client = LLMClient(_selection())
    resp = client.chat([{"role": "user", "content": "2+2?"}])

    assert isinstance(resp, LLMResponse)
    assert resp.content == "Cuatro"
    assert resp.usage is not None
    assert resp.usage.prompt_tokens == 42
    assert resp.usage.completion_tokens == 3
    assert resp.usage.total_tokens == 45


def test_chat_usage_vacio_cuando_ollama_no_lo_devuelve(monkeypatch):
    """Compatibilidad con backends que no devuelven usage."""

    class _FakeNoUsage:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json):
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}}]},
                request=request,
            )

    monkeypatch.setattr(httpx, "Client", _FakeNoUsage)
    client = LLMClient(_selection())
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.usage is None


# ---------------------------------------------------------------------------
# 2. LLMClient.stream_chat() captura usage del chunk final
# ---------------------------------------------------------------------------

class _StreamContext:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, *args):
        return False


class _FakeStreamResponse:
    is_error = False

    def read(self):
        return b""

    def raise_for_status(self):
        return None

    def iter_lines(self):
        # Chunks de contenido
        yield f"data: {json.dumps({'choices': [{'delta': {'content': 'Cua'}}]})}"
        yield f"data: {json.dumps({'choices': [{'delta': {'content': 'tro'}}]})}"
        # Chunk final con usage (antes de [DONE])
        yield f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 55, 'completion_tokens': 7, 'total_tokens': 62}})}"
        yield "data: [DONE]"


class _FakeStreamClient:
    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def stream(self, method, url, json):
        return _StreamContext(_FakeStreamResponse())


def test_stream_chat_captura_usage(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _FakeStreamClient)
    client = LLMClient(_selection())
    events = list(client.stream_chat([{"role": "user", "content": "2+2?"}]))

    stream_tokens = [e for e in events if isinstance(e, StreamToken)]
    final = next(e for e in events if isinstance(e, LLMResponse))

    assert "".join(t.text for t in stream_tokens) == "Cuatro"
    assert final.content == "Cuatro"
    assert final.usage is not None
    assert final.usage.prompt_tokens == 55
    assert final.usage.completion_tokens == 7
    assert final.usage.total_tokens == 62


def test_stream_chat_usage_en_chunk_separado(monkeypatch):
    """Ollama a veces emite el usage en un chunk con choices vacío."""

    class _FakeResponseUsageVacio:
        is_error = False

        def read(self):
            return b""

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield f"data: {json.dumps({'choices': [{'delta': {'content': 'Ok'}}]})}"
            yield f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}"
            # Chunk separado solo con usage, choices vacío
            yield f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})}"
            yield "data: [DONE]"

    class _FakeClientUsageVacio:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, json):
            return _StreamContext(_FakeResponseUsageVacio())

    monkeypatch.setattr(httpx, "Client", _FakeClientUsageVacio)
    client = LLMClient(_selection())
    events = list(client.stream_chat([{"role": "user", "content": "hi"}]))
    final = next(e for e in events if isinstance(e, LLMResponse))
    assert final.usage is not None
    assert final.usage.prompt_tokens == 10
    assert final.usage.completion_tokens == 2
    assert final.usage.total_tokens == 12


def test_build_payload_incluye_stream_options_solo_en_streaming():
    client = LLMClient(_selection())
    payload_stream = client._build_payload([], tools=None, stream=True)
    payload_no_stream = client._build_payload([], tools=None, stream=False)

    assert payload_stream.get("stream_options") == {"include_usage": True}
    assert "stream_options" not in payload_no_stream


# ---------------------------------------------------------------------------
# 3. RunLogger.record_token_stats() y run_summary.json
# ---------------------------------------------------------------------------

def _make_logger(tmp_path: Path) -> RunLogger:
    sel = _selection()
    cfg = AgentConfig(cwd=str(tmp_path), run_log_enabled=True, runs_dir=str(tmp_path / "runs"))
    from ci2lab.harness.run_logger import build_config_snapshot
    snapshot = build_config_snapshot(
        runtime_fields={"model": sel.ollama_tag},
        agent_config=cfg,
        selection=sel,
    )
    return RunLogger(
        runs_dir=tmp_path / "runs",
        selection=sel,
        agent_config=cfg,
        config_snapshot=snapshot,
        user_prompt="test",
    )


def test_run_summary_incluye_tokens(tmp_path):
    logger = _make_logger(tmp_path)
    logger.start()

    logger.record_token_stats(
        tokens_prompt_last=1500,
        tokens_prompt_peak=1800,
        tokens_completion_total=240,
    )
    logger.finalize(status="success", final_answer="ok", conversation=[], error=None)

    summaries = list((tmp_path / "runs").rglob("run_summary.json"))
    assert summaries, "No se creó run_summary.json"

    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    tokens = data["tokens"]

    assert tokens["available"] is True
    assert tokens["prompt_last_round"] == 1500
    assert tokens["prompt_peak"] == 1800
    assert tokens["completion_total"] == 240
    assert tokens["context_length"] == 32768
    assert tokens["context_used_pct"] == round(1800 / 32768 * 100, 1)


def test_run_summary_tokens_no_disponibles(tmp_path):
    """Si Ollama no devolvió usage, available=False y valores a 0."""
    logger = _make_logger(tmp_path)
    logger.start()
    # No llamamos a record_token_stats: simula que Ollama no devolvió usage
    logger.finalize(status="success", final_answer="ok", conversation=[], error=None)

    summaries = list((tmp_path / "runs").rglob("run_summary.json"))
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    tokens = data["tokens"]

    assert tokens["available"] is False
    assert tokens["prompt_peak"] == 0
    assert tokens["context_used_pct"] is None
