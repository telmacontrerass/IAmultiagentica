"""Backward-compatible facade over the pluggable LLM backends.

``LLMClient`` predates the :mod:`ci2lab.harness.backends` package and is still
the construction point used across the harness, evals and tests. It now simply
selects the backend for the given :class:`~ci2lab.contracts.types.ModelSelection`
and delegates every call to it, so existing call sites keep working unchanged
while the transport details live behind the :class:`LLMBackend` interface.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.backends import LLMBackend, LLMResponse, StreamToken, create_backend

__all__ = ["LLMClient", "LLMResponse", "StreamToken"]


class LLMClient:
    """Facade that routes chat requests to the configured backend.

    Args:
        selection: The resolved model selection; its ``backend`` field picks
            the transport (Ollama native, OpenAI-compatible, ...).
        timeout: Per-request timeout in seconds.
        vision_image_count: Number of images in the request, used only for
            clearer multimodal error messages.
    """

    def __init__(
        self,
        selection: ModelSelection,
        timeout: float = 300.0,
        *,
        vision_image_count: int = 0,
    ) -> None:
        self.selection = selection
        self.backend: LLMBackend = create_backend(
            selection, timeout, vision_image_count=vision_image_count
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any | None = None,
    ) -> LLMResponse:
        """Run a blocking chat completion via the configured backend.

        Args:
            messages: OpenAI-style chat messages to send.
            tools: Optional tool/function schemas exposed to the model.
            cancel_event: Optional event-like object that, when set, aborts the
                in-flight request.

        Returns:
            The backend's completed :class:`LLMResponse`.
        """
        return self.backend.chat(messages, tools=tools, cancel_event=cancel_event)

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any | None = None,
    ) -> Iterator[StreamToken | LLMResponse]:
        """Stream a chat completion via the configured backend.

        Args:
            messages: OpenAI-style chat messages to send.
            tools: Optional tool/function schemas exposed to the model.
            cancel_event: Optional event-like object that, when set, aborts the
                in-flight request.

        Yields:
            A :class:`StreamToken` per text fragment, followed by a single
            terminal :class:`LLMResponse`.
        """
        yield from self.backend.stream_chat(messages, tools=tools, cancel_event=cancel_event)
