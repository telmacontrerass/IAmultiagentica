"""Errores accionables del cliente LLM (Ollama)."""

from __future__ import annotations

import re
from typing import Any

import httpx


class LLMError(Exception):
    """Error de inferencia con mensaje listo para el usuario."""

    exit_code: int = 1

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.user_message = message
        self.exit_code = exit_code


class LLMConnectionError(LLMError):
    """Ollama no responde o no hay conectividad."""

    def __init__(self, detail: str = "") -> None:
        lines = [
            "No se pudo conectar con Ollama.",
            "Comprueba:",
            "1. Que Ollama esté abierto.",
            "2. Que `ollama serve` esté corriendo.",
            "3. Ejecuta `ci2lab doctor`.",
        ]
        if detail:
            lines.append(f"\nDetalle: {detail}")
        super().__init__("\n".join(lines), exit_code=2)


class LLMModelNotFoundError(LLMError):
    """El modelo solicitado no está disponible en Ollama."""

    def __init__(self, model: str, detail: str = "") -> None:
        lines = [
            f"El modelo `{model}` no parece estar disponible en Ollama.",
            "Prueba:",
            f"  ollama pull {model}",
            "  ci2lab doctor",
        ]
        if detail:
            lines.append(f"\nDetalle: {detail}")
        super().__init__("\n".join(lines), exit_code=3)


def _response_detail(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
        if isinstance(body, dict):
            return str(body.get("error") or body.get("message") or body)
        return str(body)
    except Exception:  # noqa: BLE001
        return response.text[:500]


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
    if _looks_like_model_missing(exc.response.status_code, detail, model):
        return LLMModelNotFoundError(model, detail)
    return LLMError(
        f"Error HTTP {exc.response.status_code} al contactar Ollama ({url}).\n"
        f"Detalle: {detail}\n"
        "Ejecuta `ci2lab doctor` para diagnosticar.",
        exit_code=1,
    )


def classify_request_error(exc: Exception, *, model: str, url: str) -> LLMError:
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_http_error(exc, model=model, url=url)

    if isinstance(exc, httpx.ConnectError):
        return LLMConnectionError(str(exc))

    if isinstance(exc, httpx.TimeoutException):
        return LLMConnectionError(f"Timeout al contactar {url}: {exc}")

    if isinstance(exc, httpx.RequestError):
        return LLMConnectionError(str(exc))

    text = str(exc)
    if re.search(r"model.*not found|not found.*model", text, re.I):
        return LLMModelNotFoundError(model, text)

    return LLMError(f"Error al contactar el modelo: {text}", exit_code=1)
