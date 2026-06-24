"""
Token counter tests: capture from Ollama → LLMResponse → loop → RunLogger.
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
# Shared fixture
# ---------------------------------------------------------------------------

def _selection() -> ModelSelection:
    return ModelSelection(
        model_id="qwen2.5-coder-7b",
        ollama_tag="qwen2.5-coder:7b",
        display_name="Qwen2.5 Coder 7B",
        context_length=32768,
    )


# ---------------------------------------------------------------------------
# 1. LLMClient.chat() captures usage
# ---------------------------------------------------------------------------

class _FakeChatClient:
    """Mock httpx.Client for non-streaming mode with usage in the response."""

    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json):
        request = httpx.Request("POST", url)
        # Native Ollama (/api/chat) reports usage at the top level.
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "Four"},
                "done": True,
                "prompt_eval_count": 42,
                "eval_count": 3,
            },
            request=request,
        )


def test_chat_captures_usage(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _FakeChatClient)
    client = LLMClient(_selection())
    resp = client.chat([{"role": "user", "content": "2+2?"}])

    assert isinstance(resp, LLMResponse)
    assert resp.content == "Four"
    assert resp.usage is not None
    assert resp.usage.prompt_tokens == 42
    assert resp.usage.completion_tokens == 3
    assert resp.usage.total_tokens == 45


def test_chat_usage_empty_when_ollama_does_not_return_it(monkeypatch):
    """Compatibility with backends that do not return usage."""

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
                json={"message": {"content": "ok"}, "done": True},
                request=request,
            )

    monkeypatch.setattr(httpx, "Client", _FakeNoUsage)
    client = LLMClient(_selection())
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert resp.usage is None


# ---------------------------------------------------------------------------
# 2. LLMClient.stream_chat() captures usage from the final chunk
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
        # Native streaming: newline-delimited JSON; usage rides the done chunk.
        yield json.dumps({"message": {"content": "Fo"}, "done": False})
        yield json.dumps({"message": {"content": "ur"}, "done": False})
        yield json.dumps(
            {
                "message": {"content": ""},
                "done": True,
                "prompt_eval_count": 55,
                "eval_count": 7,
            }
        )


class _FakeStreamClient:
    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def stream(self, method, url, json):
        return _StreamContext(_FakeStreamResponse())


def test_stream_chat_captures_usage(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _FakeStreamClient)
    client = LLMClient(_selection())
    events = list(client.stream_chat([{"role": "user", "content": "2+2?"}]))

    stream_tokens = [e for e in events if isinstance(e, StreamToken)]
    final = next(e for e in events if isinstance(e, LLMResponse))

    assert "".join(t.text for t in stream_tokens) == "Four"
    assert final.content == "Four"
    assert final.usage is not None
    assert final.usage.prompt_tokens == 55
    assert final.usage.completion_tokens == 7
    assert final.usage.total_tokens == 62


def test_stream_chat_usage_in_separate_chunk(monkeypatch):
    """Native streaming reports usage on the final done chunk (empty content)."""

    class _FakeResponseUsageEmpty:
        is_error = False

        def read(self):
            return b""

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield json.dumps({"message": {"content": "Ok"}, "done": False})
            # Final chunk: no new content, only the usage counts.
            yield json.dumps(
                {
                    "message": {"content": ""},
                    "done": True,
                    "prompt_eval_count": 10,
                    "eval_count": 2,
                }
            )

    class _FakeClientUsageEmpty:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, json):
            return _StreamContext(_FakeResponseUsageEmpty())

    monkeypatch.setattr(httpx, "Client", _FakeClientUsageEmpty)
    client = LLMClient(_selection())
    events = list(client.stream_chat([{"role": "user", "content": "hi"}]))
    final = next(e for e in events if isinstance(e, LLMResponse))
    assert final.usage is not None
    assert final.usage.prompt_tokens == 10
    assert final.usage.completion_tokens == 2
    assert final.usage.total_tokens == 12


def test_build_payload_includes_stream_options_only_in_streaming():
    client = LLMClient(_selection())
    payload_stream = client._build_payload([], tools=None, stream=True)
    payload_no_stream = client._build_payload([], tools=None, stream=False)

    assert payload_stream.get("stream_options") == {"include_usage": True}
    assert "stream_options" not in payload_no_stream


# ---------------------------------------------------------------------------
# 3. RunLogger.record_token_stats() and run_summary.json
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


def test_run_summary_includes_tokens(tmp_path):
    logger = _make_logger(tmp_path)
    logger.start()

    logger.record_token_stats(
        tokens_prompt_last=1500,
        tokens_prompt_peak=1800,
        tokens_completion_total=240,
    )
    logger.finalize(status="success", final_answer="ok", conversation=[], error=None)

    summaries = list((tmp_path / "runs").rglob("run_summary.json"))
    assert summaries, "run_summary.json was not created"

    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    tokens = data["tokens"]

    assert tokens["available"] is True
    assert tokens["prompt_last_round"] == 1500
    assert tokens["prompt_peak"] == 1800
    assert tokens["completion_total"] == 240
    assert tokens["context_length"] == 32768
    assert tokens["context_used_pct"] == round(1800 / 32768 * 100, 1)


def test_run_summary_tokens_not_available(tmp_path):
    """If Ollama did not return usage, available=False and values at 0."""
    logger = _make_logger(tmp_path)
    logger.start()
    # We do not call record_token_stats: simulates Ollama not returning usage
    logger.finalize(status="success", final_answer="ok", conversation=[], error=None)

    summaries = list((tmp_path / "runs").rglob("run_summary.json"))
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    tokens = data["tokens"]

    assert tokens["available"] is False
    assert tokens["prompt_peak"] == 0
    assert tokens["context_used_pct"] is None
