"""Backend for OpenAI-compatible ``/v1/chat/completions`` servers.

This covers any server that speaks the OpenAI Chat Completions wire format —
vLLM, LM Studio, llama.cpp's server, Text Generation Inference, and Ollama's
own ``/v1`` shim. Pointing the agent at one of these requires only setting the
backend and base URL in configuration; no code changes.
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


class OpenAICompatBackend(LLMBackend):
    """Talks to any OpenAI Chat Completions-compatible inference server."""

    def __init__(
        self,
        selection: ModelSelection,
        timeout: float = 300.0,
        *,
        vision_image_count: int = 0,
    ) -> None:
        super().__init__(selection, timeout, vision_image_count=vision_image_count)
        base = selection.backend_url.rstrip("/")
        self.chat_url = f"{base}/chat/completions"

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        stream: bool,
        model: str,
    ) -> dict[str, Any]:
        """Build an OpenAI ``/v1/chat/completions`` request body."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.selection.temperature,
            "max_tokens": self.selection.max_tokens,
            "stream": stream,
        }
        if tools and self.selection.supports_tools and self.selection.tool_mode == "native":
            payload["tools"] = tools
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    @staticmethod
    def _parse_response(
        choice: dict[str, Any],
        *,
        usage: TokenUsage | None = None,
    ) -> LLMResponse:
        """Parse a single OpenAI ``choices[*]`` entry into an :class:`LLMResponse`."""
        message = choice.get("message") or choice.get("delta") or {}
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        return LLMResponse(content=content, tool_calls=tool_calls, raw=choice, usage=usage)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any | None = None,
    ) -> LLMResponse:
        """Run a blocking chat completion against the OpenAI-compatible endpoint."""
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
                        usage = TokenUsage.from_provider(data.get("usage"), model=model)
                        return self._parse_response(data["choices"][0], usage=usage)
                    except Exception as exc:
                        self._raise_if_cancelled(cancel_event)
                        err = classify_request_error(
                            exc,
                            model=model,
                            url=self.chat_url,
                            num_images=self.vision_image_count,
                            backend="openai",
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
        """Stream a chat completion from the OpenAI-compatible endpoint."""
        with httpx.Client(timeout=self.timeout) as client:
            done = self._watch_cancellation(client, cancel_event)
            try:
                for model in self._model_candidates():
                    self._raise_if_cancelled(cancel_event)
                    content_parts: list[str] = []
                    tool_calls_acc: dict[int, dict[str, Any]] = {}
                    usage: TokenUsage | None = None
                    emitted_tokens = False
                    payload = self._build_payload(messages, tools=tools, stream=True, model=model)

                    try:
                        with client.stream("POST", self.chat_url, json=payload) as response:
                            if getattr(response, "is_error", False):
                                response.read()
                            response.raise_for_status()
                            self.selection.ollama_tag = model
                            for line in response.iter_lines():
                                self._raise_if_cancelled(cancel_event)
                                if not line or not line.startswith("data: "):
                                    continue
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                except json.JSONDecodeError:
                                    continue
                                choices = chunk.get("choices") or []
                                chunk_usage = TokenUsage.from_provider(
                                    chunk.get("usage"), model=model
                                )
                                if chunk_usage is not None:
                                    usage = chunk_usage
                                if not choices:
                                    continue
                                delta = choices[0].get("delta") or {}
                                if delta.get("content"):
                                    piece = delta["content"]
                                    content_parts.append(piece)
                                    emitted_tokens = True
                                    yield StreamToken(text=piece)
                                for tc in delta.get("tool_calls") or []:
                                    self._accumulate_tool_call(tool_calls_acc, tc)
                    except Exception as exc:
                        self._raise_if_cancelled(cancel_event)
                        err = classify_request_error(
                            exc,
                            model=model,
                            url=self.chat_url,
                            num_images=self.vision_image_count,
                            backend="openai",
                        )
                        if (
                            isinstance(err, LLMModelNotFoundError)
                            and not emitted_tokens
                            and model != self._model_candidates()[-1]
                        ):
                            continue
                        raise err from exc

                    self._raise_if_cancelled(cancel_event)
                    tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
                    yield LLMResponse(
                        content="".join(content_parts),
                        tool_calls=tool_calls,
                        raw={},
                        usage=usage,
                    )
                    return
            finally:
                if done is not None:
                    done.set()

        raise LLMModelNotFoundError(self.selection.ollama_tag)

    @staticmethod
    def _accumulate_tool_call(
        acc: dict[int, dict[str, Any]],
        delta: dict[str, Any],
    ) -> None:
        """Merge one streamed tool-call delta into the per-index accumulator.

        OpenAI streams tool calls as indexed fragments: the name arrives once
        and ``arguments`` accrue character-by-character across chunks.
        """
        idx = delta.get("index", 0)
        entry = acc.setdefault(
            idx,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if delta.get("id"):
            entry["id"] = delta["id"]
        fn = delta.get("function") or {}
        if fn.get("name"):
            entry["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            entry["function"]["arguments"] += fn["arguments"]
