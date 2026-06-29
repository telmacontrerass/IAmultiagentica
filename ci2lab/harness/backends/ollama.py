"""Backend for the native Ollama ``/api/chat`` endpoint.

The native endpoint is used in preference to Ollama's OpenAI-compatible
``/v1`` path because only the native one honours ``options.num_ctx`` — the
context window the model actually loads. The ``/v1`` endpoint silently ignores
it and falls back to a small server default (~4k tokens), which makes the model
"forget" earlier turns even though the harness budgeted for the full window.
Sending ``num_ctx = context_length`` keeps the real window and the harness's
compaction math in agreement.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.backends.base import LLMBackend, LLMResponse, StreamToken
from ci2lab.harness.llm_errors import (
    LLMModelNotFoundError,
    classify_request_error,
)
from ci2lab.harness.token_usage import TokenUsage


class OllamaBackend(LLMBackend):
    """Talks to a local Ollama server over its native chat protocol."""

    def __init__(
        self,
        selection: ModelSelection,
        timeout: float = 300.0,
        *,
        vision_image_count: int = 0,
    ) -> None:
        super().__init__(selection, timeout, vision_image_count=vision_image_count)
        base = selection.backend_url.rstrip("/")
        # The native endpoint lives at the server root, not under ``/v1``.
        native_base = base[:-3].rstrip("/") if base.endswith("/v1") else base
        self.chat_url = f"{native_base}/api/chat"

    def _num_ctx(self) -> int:
        """Return the configured context window in tokens (0 when unknown)."""
        try:
            return max(0, int(self.selection.context_length or 0))
        except (TypeError, ValueError):
            return 0

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        stream: bool,
        model: str,
    ) -> dict[str, Any]:
        """Build a native ``/api/chat`` request body.

        ``num_ctx`` is the whole point of using this endpoint: it makes the
        server load the context window the harness assumes it has.
        """
        options: dict[str, Any] = {"temperature": self.selection.temperature}
        num_ctx = self._num_ctx()
        if num_ctx > 0:
            options["num_ctx"] = num_ctx
        if self.selection.max_tokens:
            options["num_predict"] = self.selection.max_tokens
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._to_native_messages(messages),
            "stream": stream,
            "options": options,
        }
        if tools and self.selection.supports_tools and self.selection.tool_mode == "native":
            payload["tools"] = tools
        return payload

    @staticmethod
    def _to_native_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Adapt the harness's OpenAI-shaped history to Ollama's native format.

        History is stored OpenAI-style (for the ``/v1`` path and session files):
        tool-call ``arguments`` are a JSON *string* and tool results carry a
        ``tool_call_id``. Ollama's native ``/api/chat`` instead wants
        ``arguments`` as a JSON *object* and a bare ``{role: tool, content}`` —
        sending the OpenAI shape makes it reject the request once a prior tool
        call is replayed.

        Multimodal messages are also converted: OpenAI uses a *list* of typed
        content blocks, while Ollama native uses a plain ``content`` string plus
        a separate ``images`` list of raw base64 strings (no data-URL prefix).
        """
        converted: list[dict[str, Any]] = []
        for msg in messages:
            raw_calls = msg.get("tool_calls")
            if raw_calls:
                native_calls = []
                for tc in raw_calls:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args) if args.strip() else {}
                        except json.JSONDecodeError:
                            args = {}
                    elif not isinstance(args, dict):
                        args = {}
                    native_calls.append(
                        {"function": {"name": fn.get("name", ""), "arguments": args}}
                    )
                new_msg = {k: v for k, v in msg.items() if k != "tool_calls"}
                new_msg["tool_calls"] = native_calls
                converted.append(new_msg)
            elif msg.get("role") == "tool":
                # Native tool result: role + content only (no tool_call_id).
                converted.append({"role": "tool", "content": msg.get("content", "")})
            elif isinstance(msg.get("content"), list):
                # Multimodal message: OpenAI list-of-blocks -> Ollama native.
                # Collect text parts and base64 image data separately.
                text_parts: list[str] = []
                images: list[str] = []
                for block in msg["content"]:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text") or "")
                    elif block.get("type") == "image_url":
                        url = (block.get("image_url") or {}).get("url", "")
                        # Strip "data:image/TYPE;base64," prefix -> raw base64.
                        if ";base64," in url:
                            images.append(url.split(";base64,", 1)[1])
                new_msg = {k: v for k, v in msg.items() if k != "content"}
                new_msg["content"] = " ".join(text_parts)
                if images:
                    new_msg["images"] = images
                converted.append(new_msg)
            else:
                converted.append(msg)
        return converted

    @staticmethod
    def _parse_response(data: dict[str, Any], *, model: str) -> LLMResponse:
        """Parse a non-streaming native response into an :class:`LLMResponse`."""
        message = data.get("message") or {}
        content = message.get("content") or ""
        # Native tool_calls carry ``function.arguments`` as an object, which the
        # downstream parser already accepts.
        tool_calls = message.get("tool_calls") or []
        # Native usage is reported at the top level as prompt_eval_count /
        # eval_count, which TokenUsage.from_provider already understands.
        usage = TokenUsage.from_provider(data, model=model)
        return LLMResponse(content=content, tool_calls=tool_calls, raw=data, usage=usage)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any | None = None,
    ) -> LLMResponse:
        """Run a blocking chat completion against the Ollama native endpoint."""
        with httpx.Client(timeout=self.timeout) as client:
            done = self._watch_cancellation(client, cancel_event)
            try:
                for model in self._model_candidates():
                    self._raise_if_cancelled(cancel_event)
                    payload = self._build_payload(messages, tools=tools, stream=False, model=model)
                    try:
                        response = client.post(self.chat_url, json=payload)
                        response.raise_for_status()
                        data = response.json()
                        self.selection.ollama_tag = model
                        return self._parse_response(data, model=model)
                    except Exception as exc:
                        self._raise_if_cancelled(cancel_event)
                        err = classify_request_error(
                            exc,
                            model=model,
                            url=self.chat_url,
                            num_images=self.vision_image_count,
                        )
                        if (
                            isinstance(err, LLMModelNotFoundError)
                            and model != self._model_candidates()[-1]
                        ):
                            continue
                        raise err from exc
            finally:
                if done is not None:
                    done.set()

        raise LLMModelNotFoundError(self.selection.ollama_tag)

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any | None = None,
    ) -> Iterator[StreamToken | LLMResponse]:
        """Stream a chat completion from the Ollama native endpoint."""
        with httpx.Client(timeout=self.timeout) as client:
            done = self._watch_cancellation(client, cancel_event)
            try:
                for model in self._model_candidates():
                    self._raise_if_cancelled(cancel_event)
                    content_parts: list[str] = []
                    tool_calls_acc: list[dict[str, Any]] = []
                    usage: TokenUsage | None = None
                    emitted_tokens = False
                    payload = self._build_payload(messages, tools=tools, stream=True, model=model)

                    try:
                        with client.stream("POST", self.chat_url, json=payload) as response:
                            if getattr(response, "is_error", False):
                                response.read()
                            response.raise_for_status()
                            self.selection.ollama_tag = model
                            # Native streaming is newline-delimited JSON objects,
                            # not SSE ``data:`` frames.
                            for line in response.iter_lines():
                                self._raise_if_cancelled(cancel_event)
                                text = line.strip() if line else ""
                                if not text:
                                    continue
                                try:
                                    chunk = json.loads(text)
                                except json.JSONDecodeError:
                                    continue
                                message = chunk.get("message") or {}
                                piece = message.get("content")
                                if piece:
                                    content_parts.append(piece)
                                    emitted_tokens = True
                                    yield StreamToken(text=piece)
                                # Ollama emits each tool call whole (no
                                # OpenAI-style per-fragment deltas).
                                for tc in message.get("tool_calls") or []:
                                    tool_calls_acc.append(tc)
                                if chunk.get("done"):
                                    chunk_usage = TokenUsage.from_provider(chunk, model=model)
                                    if chunk_usage is not None:
                                        usage = chunk_usage
                    except Exception as exc:
                        self._raise_if_cancelled(cancel_event)
                        err = classify_request_error(
                            exc,
                            model=model,
                            url=self.chat_url,
                            num_images=self.vision_image_count,
                        )
                        if (
                            isinstance(err, LLMModelNotFoundError)
                            and not emitted_tokens
                            and model != self._model_candidates()[-1]
                        ):
                            continue
                        raise err from exc

                    self._raise_if_cancelled(cancel_event)
                    yield LLMResponse(
                        content="".join(content_parts),
                        tool_calls=tool_calls_acc,
                        raw={},
                        usage=usage,
                    )
                    return
            finally:
                if done is not None:
                    done.set()

        raise LLMModelNotFoundError(self.selection.ollama_tag)
