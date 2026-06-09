import httpx

from ci2lab.harness.llm_errors import (
    LLMConnectionError,
    LLMModelNotFoundError,
    classify_request_error,
)


def test_classify_connect_error():
    exc = httpx.ConnectError("connection refused")
    err = classify_request_error(exc, model="m:1", url="http://localhost:11434/v1/chat/completions")
    assert isinstance(err, LLMConnectionError)
    assert "No se pudo conectar" in err.user_message
    assert err.exit_code == 2


def test_classify_model_not_found():
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    response = httpx.Response(404, json={"error": "model 'missing:1b' not found"}, request=request)
    exc = httpx.HTTPStatusError("404", request=request, response=response)
    err = classify_request_error(exc, model="missing:1b", url="http://localhost/v1/chat/completions")
    assert isinstance(err, LLMModelNotFoundError)
    assert "ollama pull" in err.user_message
    assert err.exit_code == 3
