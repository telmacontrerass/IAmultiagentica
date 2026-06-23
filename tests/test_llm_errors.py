import httpx

from ci2lab.harness.llm_errors import (
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMTimeoutError,
    classify_request_error,
)


def test_classify_connect_error():
    exc = httpx.ConnectError("connection refused")
    err = classify_request_error(exc, model="m:1", url="http://localhost:11434/v1/chat/completions")
    assert isinstance(err, LLMConnectionError)
    assert "Could not connect" in err.user_message
    assert err.exit_code == 2


def test_classify_model_not_found():
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    response = httpx.Response(404, json={"error": "model 'missing:1b' not found"}, request=request)
    exc = httpx.HTTPStatusError("404", request=request, response=response)
    err = classify_request_error(exc, model="missing:1b", url="http://localhost/v1/chat/completions")
    assert isinstance(err, LLMModelNotFoundError)
    assert "ollama pull" in err.user_message
    assert err.exit_code == 3


def test_classify_timeout_with_vision_images():
    exc = httpx.ReadTimeout("timed out")
    err = classify_request_error(
        exc,
        model="qwen2.5vl:7b",
        url="http://localhost:11434/api/chat",
        num_images=2,
    )
    assert isinstance(err, LLMTimeoutError)
    assert "did not respond in time" in err.user_message
    assert "Vision requests" in err.user_message
    assert "Could not connect" not in err.user_message
