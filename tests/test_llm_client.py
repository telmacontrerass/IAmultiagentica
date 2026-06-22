import json
import threading
import time

import httpx
import pytest

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import LLMCancelledError
from ci2lab.harness.llm_client import LLMClient, LLMResponse, StreamToken


def _selection() -> ModelSelection:
    return ModelSelection(
        model_id="qwen2.5-coder-1.5b",
        ollama_tag="qwen2.5-coder:1.5b",
        display_name="Qwen2.5 Coder 1.5B",
    )


def test_chat_retries_with_model_id_when_ollama_tag_is_missing(monkeypatch):
    calls: list[str] = []

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json):
            calls.append(json["model"])
            request = httpx.Request("POST", url)
            if len(calls) == 1:
                return httpx.Response(
                    404,
                    json={"error": "model qwen2.5-coder:1.5b not found"},
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {
                        "prompt_tokens": 7,
                        "completion_tokens": 2,
                        "total_tokens": 9,
                    },
                },
                request=request,
            )

    monkeypatch.setattr(httpx, "Client", FakeClient)

    client = LLMClient(_selection())
    result = client.chat([{"role": "user", "content": "hola"}])

    assert isinstance(result, LLMResponse)
    assert result.content == "ok"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 7
    assert result.usage.completion_tokens == 2
    assert result.usage.total_tokens == 9
    assert calls == ["qwen2.5-coder:1.5b", "qwen2.5-coder-1.5b"]
    assert client.selection.ollama_tag == "qwen2.5-coder-1.5b"


def test_chat_cancel_event_closes_blocking_client(monkeypatch):
    cancel_event = threading.Event()
    closed_clients = []

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout
            self.closed = False
            closed_clients.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def close(self):
            self.closed = True

        def post(self, url, json):
            cancel_event.set()
            deadline = time.time() + 2
            while not self.closed and time.time() < deadline:
                time.sleep(0.01)
            raise httpx.ReadError("closed", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "Client", FakeClient)

    client = LLMClient(_selection())
    with pytest.raises(LLMCancelledError):
        client.chat([{"role": "user", "content": "hola"}], cancel_event=cancel_event)

    assert closed_clients
    assert closed_clients[0].closed is True


def test_stream_chat_retries_with_model_id_when_ollama_tag_is_missing(monkeypatch):
    calls: list[str] = []

    class StreamContext:
        def __init__(self, response):
            self.response = response

        def __enter__(self):
            return self.response

        def __exit__(self, *args):
            return False

    class GoodStreamResponse:
        is_error = False

        def read(self):
            return b""

        def raise_for_status(self):
            return None

        def iter_lines(self):
            chunk = {"choices": [{"delta": {"content": "ok"}}]}
            yield f"data: {json.dumps(chunk)}"
            usage = {
                "choices": [],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                    "total_tokens": 4,
                },
            }
            yield f"data: {json.dumps(usage)}"
            yield "data: [DONE]"

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, json):
            calls.append(json["model"])
            request = httpx.Request(method, url)
            if len(calls) == 1:
                response = httpx.Response(
                    404,
                    json={"error": "model qwen2.5-coder:1.5b not found"},
                    request=request,
                )
            else:
                response = GoodStreamResponse()
            return StreamContext(response)

    monkeypatch.setattr(httpx, "Client", FakeClient)

    client = LLMClient(_selection())
    events = list(client.stream_chat([{"role": "user", "content": "hola"}]))

    assert isinstance(events[0], StreamToken)
    assert events[0].text == "ok"
    assert isinstance(events[-1], LLMResponse)
    assert events[-1].content == "ok"
    assert events[-1].usage is not None
    assert events[-1].usage.total_tokens == 4
    assert calls == ["qwen2.5-coder:1.5b", "qwen2.5-coder-1.5b"]
    assert client.selection.ollama_tag == "qwen2.5-coder-1.5b"
