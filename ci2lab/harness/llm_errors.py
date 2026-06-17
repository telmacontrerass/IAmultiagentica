"""Actionable errors for the LLM client (Ollama)."""

from __future__ import annotations

import re
from typing import Any

import httpx


class LLMError(Exception):
    """Inference error with a user-ready message."""

    exit_code: int = 1

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.user_message = message
        self.exit_code = exit_code


class LLMConnectionError(LLMError):
    """Ollama is not responding or there is no connectivity."""

    def __init__(self, detail: str = "") -> None:
        lines = [
            "Could not connect to Ollama.",
            "Check:",
            "1. That Ollama is open.",
            "2. That `ollama serve` is running.",
            "3. Run `ci2lab doctor`.",
        ]
        if detail:
            lines.append(f"\nDetail: {detail}")
        super().__init__("\n".join(lines), exit_code=2)


class LLMModelNotFoundError(LLMError):
    """The requested model is not available in Ollama."""

    def __init__(self, model: str, detail: str = "") -> None:
        lines = [
            f"The model `{model}` does not appear to be available in Ollama.",
            "Try:",
            f"  ollama pull {model}",
            "  ci2lab doctor",
        ]
        if detail:
            lines.append(f"\nDetail: {detail}")
        super().__init__("\n".join(lines), exit_code=3)


def _response_detail(response: httpx.Response) -> str:
    try:
        response.read()
    except Exception as exc:  # noqa: BLE001
        return str(exc)

    try:
        body: Any = response.json()
        if isinstance(body, dict):
            return str(body.get("error") or body.get("message") or body)
        return str(body)
    except Exception as exc:  # noqa: BLE001
        try:
            return response.text[:500]
        except Exception:  # noqa: BLE001
            return str(exc)


def _looks_like_model_missing(status: int, detail: str, model: str) -> bool:
    if status not in (400, 404, 422, 500):
        return False
    low = detail.lower()
    model_low = model.lower()
    patterns = (
        "not found",
        "does not exist",
        "no such model",
        "unknown model",
        "model '" in low,
        'model "' in low,
    )
    if any(p in low if isinstance(p, str) else p for p in patterns):
        return True
    return model_low in low and ("model" in low or "pull" in low)


def classify_http_error(
    exc: httpx.HTTPStatusError,
    *,
    model: str,
    url: str,
) -> LLMError:
    detail = _response_detail(exc.response)
    if exc.response.status_code == 404 or _looks_like_model_missing(
        exc.response.status_code,
        detail,
        model,
    ):
        return LLMModelNotFoundError(model, detail)
    return LLMError(
        f"HTTP error {exc.response.status_code} contacting Ollama ({url}).\n"
        f"Detail: {detail}\n"
        "Run `ci2lab doctor` to diagnose.",
        exit_code=1,
    )


def classify_request_error(exc: Exception, *, model: str, url: str) -> LLMError:
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_http_error(exc, model=model, url=url)

    if isinstance(exc, httpx.ConnectError):
        return LLMConnectionError(str(exc))

    if isinstance(exc, httpx.TimeoutException):
        return LLMConnectionError(f"Timeout contacting {url}: {exc}")

    if isinstance(exc, httpx.RequestError):
        return LLMConnectionError(str(exc))

    text = str(exc)
    if re.search(r"model.*not found|not found.*model", text, re.I):
        return LLMModelNotFoundError(model, text)

    return LLMError(f"Error contacting the model: {text}", exit_code=1)
