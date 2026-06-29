"""Pluggable LLM transports.

Public API for talking to an inference server without knowing which one it is.
Choose a backend with :func:`create_backend` and exchange messages via the
:class:`LLMBackend` interface, which speaks in :class:`LLMResponse` /
:class:`StreamToken`.
"""

from __future__ import annotations

from ci2lab.harness.backends.base import LLMBackend, LLMResponse, StreamToken
from ci2lab.harness.backends.factory import create_backend
from ci2lab.harness.backends.ollama import OllamaBackend
from ci2lab.harness.backends.openai_compat import OpenAICompatBackend

__all__ = [
    "LLMBackend",
    "LLMResponse",
    "OllamaBackend",
    "OpenAICompatBackend",
    "StreamToken",
    "create_backend",
]
