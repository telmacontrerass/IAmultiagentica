"""Transport-agnostic LLM backend contract and shared HTTP plumbing.

A *backend* is the only component that knows how to talk to a concrete
inference server (its wire protocol, endpoints and payload shape). Everything
above the backend speaks in terms of :class:`LLMResponse` / :class:`StreamToken`
and never imports a provider-specific module. Swapping the underlying
open-source model — or the server that runs it — therefore means choosing a
different backend, which is driven entirely by configuration (see
:func:`ci2lab.harness.backends.factory.create_backend`).
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import LLMCancelledError
from ci2lab.harness.token_usage import TokenUsage


@dataclass
class LLMResponse:
    """A single completed assistant turn returned by a backend.

    Attributes:
        content: The assistant's text output (may be empty when the turn is a
            pure tool call).
        tool_calls: Raw tool-call dictionaries exactly as the provider emitted
            them; downstream parsing normalises these into
            :class:`~ci2lab.harness.types.ToolCall` objects.
        raw: The provider's raw response payload, retained for debugging.
        usage: Token-accounting for the call, when the provider reports it.
    """

    content: str
    tool_calls: list[dict[str, Any]]
    raw: dict[str, Any] = field(default_factory=dict)
    usage: TokenUsage | None = None


@dataclass
class StreamToken:
    """An incremental text fragment yielded while a response streams."""

    text: str


class LLMBackend(ABC):
    """Abstract transport to a chat-completions service.

    Concrete subclasses implement :meth:`chat` and :meth:`stream_chat` for one
    wire protocol. Shared concerns — model-tag fallback and cooperative
    cancellation — live here so every backend behaves identically.

    Args:
        selection: The resolved model selection (model tag, backend URL,
            context window, sampling parameters). Backends may mutate
            ``selection.ollama_tag`` to record the concrete tag that the server
            actually accepted.
        timeout: Per-request timeout in seconds.
        vision_image_count: Number of images in the request; used only to
            produce clearer error messages for multimodal failures.

    Attributes:
        chat_url: The fully-qualified chat-completions endpoint; each concrete
            backend sets this in its ``__init__``.
    """

    chat_url: str

    def __init__(
        self,
        selection: ModelSelection,
        timeout: float = 300.0,
        *,
        vision_image_count: int = 0,
    ) -> None:
        self.selection = selection
        self.timeout = timeout
        self.vision_image_count = vision_image_count

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any | None = None,
    ) -> LLMResponse:
        """Run a blocking chat completion and return the full response."""

    @abstractmethod
    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any | None = None,
    ) -> Iterator[StreamToken | LLMResponse]:
        """Stream a chat completion.

        Yields a :class:`StreamToken` per text fragment and finishes with a
        single :class:`LLMResponse` carrying the assembled content, tool calls
        and usage.
        """

    def _model_candidates(self) -> list[str]:
        """Return the ordered model tags to try for this request.

        The catalog ``ollama_tag`` is preferred. Catalog ids are often
        slugified (``"phi4-14b"``) and are not valid server model names, so a
        colon-bearing ``model_id`` is appended as a fallback only.
        """
        candidates = [self.selection.ollama_tag]
        model_id = (self.selection.model_id or "").strip()
        if model_id and model_id != self.selection.ollama_tag and ":" in model_id:
            candidates.append(model_id)
        unique: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in unique:
                unique.append(candidate)
        return unique

    @staticmethod
    def _raise_if_cancelled(cancel_event: Any | None) -> None:
        """Raise :class:`LLMCancelledError` if the cancel event is set."""
        if cancel_event is not None and cancel_event.is_set():
            raise LLMCancelledError()

    @staticmethod
    def _watch_cancellation(
        client: httpx.Client,
        cancel_event: Any | None,
    ) -> threading.Event | None:
        """Start a watcher thread that closes ``client`` on cancellation.

        Returns the watcher's "done" event so the caller can stop it in a
        ``finally`` block, or ``None`` when there is nothing to watch.
        """
        if cancel_event is None:
            return None
        done = threading.Event()

        def watch() -> None:
            while not done.wait(0.1):
                if cancel_event.is_set():
                    client.close()
                    return

        threading.Thread(target=watch, name="ci2lab-llm-cancel", daemon=True).start()
        return done
