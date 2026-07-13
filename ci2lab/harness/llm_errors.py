"""Actionable errors for LLM backends."""

from __future__ import annotations

import re
from typing import Any

import httpx


class LLMError(Exception):
    """Inference error with a user-ready message."""

    exit_code: int = 1

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        """Initialize the error.

        Args:
            message: User-ready message, also exposed as ``user_message``.
            exit_code: Process exit code to surface for this failure.
        """
        super().__init__(message)
        self.user_message = message
        self.exit_code = exit_code


class LLMTimeoutError(LLMError):
    """The model did not respond within the allowed time."""

    def __init__(
        self,
        detail: str = "",
        *,
        num_images: int = 0,
        backend: str = "ollama",
    ) -> None:
        """Build a timeout error with guidance tailored to the request.

        Args:
            detail: Optional low-level detail appended to the message.
            num_images: Number of attached images/PDF pages; when positive, the
                message includes vision-specific advice.
        """
        lines = [
            "The model did not respond in time.",
        ]
        if num_images > 0:
            lines.extend(
                [
                    "Vision requests with attached images or PDF pages can take several",
                    "minutes on CPU-bound hardware — especially the first run while the",
                    "model loads.",
                    "Try:",
                    "  - Wait and retry (a 2-page PDF may need 5–10 minutes)",
                    "  - Use a smaller vision model (e.g. moondream, llava:7b)",
                    "  - Attach fewer pages or a single PNG instead of a PDF",
                ]
            )
        else:
            lines.extend(_backend_connection_guidance(backend))
        if detail:
            lines.append(f"\nDetail: {detail}")
        super().__init__("\n".join(lines), exit_code=2)


class LLMConnectionError(LLMError):
    """The configured inference backend is not responding."""

    def __init__(self, detail: str = "", *, backend: str = "ollama") -> None:
        """Build a connection error.

        Args:
            detail: Optional low-level detail appended to the message.
        """
        if backend == "ollama":
            lines = [
                "Could not connect to Ollama.",
                "Check:",
                "1. That Ollama is open.",
                "2. That `ollama serve` is running.",
                "3. Run `ci2lab doctor`.",
            ]
        else:
            lines = [
                "Could not connect to the OpenAI-compatible backend.",
                "Check:",
                "1. That the local inference server is running.",
                "2. That `--base-url` / `CI2LAB_BACKEND_URL` points at the /v1 base URL.",
                "3. That `/v1/chat/completions` is reachable.",
                "4. Run `ci2lab doctor --backend openai --base-url <url>`.",
            ]
        if detail:
            lines.append(f"\nDetail: {detail}")
        super().__init__("\n".join(lines), exit_code=2)


class LLMModelNotFoundError(LLMError):
    """The requested model is not available from the backend."""

    def __init__(self, model: str, detail: str = "", *, backend: str = "ollama") -> None:
        """Build a model-not-found error.

        Args:
            model: Requested model tag that could not be located.
            detail: Optional low-level detail appended to the message.
        """
        if backend == "ollama":
            lines = [
                f"The model `{model}` does not appear to be available in Ollama.",
                "Try:",
                f"  ollama pull {model}",
                "  ci2lab doctor",
            ]
        else:
            lines = [
                f"The model `{model}` does not appear to be available from the backend.",
                "Try:",
                "  - Check the model name served by the local inference server.",
                "  - Check `--base-url` / `CI2LAB_BACKEND_URL` points at the /v1 base URL.",
                "  - Check that `/v1/chat/completions` is reachable.",
                "  - Run `ci2lab doctor --backend openai --base-url <url>`.",
            ]
        if detail:
            lines.append(f"\nDetail: {detail}")
        super().__init__("\n".join(lines), exit_code=3)


class LLMCancelledError(LLMError):
    """The active inference request was cancelled by the caller."""

    def __init__(self) -> None:
        """Build a cancellation error with exit code 130."""
        super().__init__("Stopped by the user.", exit_code=130)


def _response_detail(response: httpx.Response) -> str:
    """Extract a short, human-readable detail string from an HTTP response."""
    try:
        response.read()
    except Exception as exc:
        return str(exc)

    try:
        body: Any = response.json()
        if isinstance(body, dict):
            return str(body.get("error") or body.get("message") or body)
        return str(body)
    except Exception as exc:
        try:
            return response.text[:500]
        except Exception:
            return str(exc)


def _looks_like_model_missing(status: int, detail: str, model: str) -> bool:
    """Heuristically decide whether an error indicates a missing model.

    Args:
        status: HTTP status code of the failed response.
        detail: Detail text extracted from the response body.
        model: Requested model tag.

    Returns:
        ``True`` when the status and detail look like a model-not-found error.
    """
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
    backend: str = "ollama",
) -> LLMError:
    """Map an HTTP status error to a specific :class:`LLMError`.

    Args:
        exc: The raised ``httpx`` status error.
        model: Requested model tag, used for model-not-found detection.
        url: Endpoint URL contacted, included in generic error messages.

    Returns:
        An :class:`LLMModelNotFoundError` when the response looks like a missing
        model, otherwise a generic :class:`LLMError`.
    """
    detail = _response_detail(exc.response)
    if exc.response.status_code == 404 or _looks_like_model_missing(
        exc.response.status_code,
        detail,
        model,
    ):
        return LLMModelNotFoundError(model, detail, backend=backend)
    provider = "Ollama" if backend == "ollama" else "OpenAI-compatible backend"
    return LLMError(
        f"HTTP error {exc.response.status_code} contacting {provider} ({url}).\n"
        f"Detail: {detail}\n"
        "Run `ci2lab doctor` to diagnose.",
        exit_code=1,
    )


def classify_request_error(
    exc: Exception,
    *,
    model: str,
    url: str,
    num_images: int = 0,
    backend: str = "ollama",
) -> LLMError:
    """Map an arbitrary request exception to a specific :class:`LLMError`.

    Dispatches on the ``httpx`` exception type (status, connection, timeout,
    generic request) and falls back to a string-pattern check for missing-model
    errors before returning a generic :class:`LLMError`.

    Args:
        exc: The raised exception.
        model: Requested model tag, used for model-not-found detection.
        url: Endpoint URL contacted, included in error messages.
        num_images: Number of attached images/PDF pages; forwarded to timeout
            errors so they can show vision-specific guidance.

    Returns:
        The most specific :class:`LLMError` subclass that matches ``exc``.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_http_error(exc, model=model, url=url, backend=backend)

    if isinstance(exc, httpx.ConnectError):
        return LLMConnectionError(str(exc), backend=backend)

    if isinstance(exc, httpx.TimeoutException):
        return LLMTimeoutError(
            f"Timeout contacting {url}: {exc}",
            num_images=num_images,
            backend=backend,
        )

    if isinstance(exc, httpx.RequestError):
        return LLMConnectionError(str(exc), backend=backend)

    text = str(exc)
    if re.search(r"model.*not found|not found.*model", text, re.I):
        return LLMModelNotFoundError(model, text, backend=backend)

    return LLMError(f"Error contacting the model: {text}", exit_code=1)


def _backend_connection_guidance(backend: str) -> list[str]:
    if backend == "ollama":
        return [
            "Check that Ollama is running (`ollama serve`) and try again.",
            "Run `ci2lab doctor` to diagnose.",
        ]
    return [
        "Check that the local OpenAI-compatible server is running.",
        "Check `--base-url` / `CI2LAB_BACKEND_URL` and the `/v1/chat/completions` endpoint.",
        "Run `ci2lab doctor --backend openai --base-url <url>` to diagnose.",
    ]
