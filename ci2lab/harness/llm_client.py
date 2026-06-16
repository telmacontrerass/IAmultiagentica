"""Cliente HTTP OpenAI-compatible (Ollama / vLLM)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import LLMModelNotFoundError, classify_request_error
from ci2lab.harness.token_usage import TokenUsage


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict[str, Any]]
    raw: dict[str, Any] = field(default_factory=dict)
    usage: TokenUsage | None = None


@dataclass
class StreamToken:
    text: str


class LLMClient:
    def __init__(self, selection: ModelSelection, timeout: float = 300.0) -> None:
        self.selection = selection
        self.timeout = timeout
        base = selection.backend_url.rstrip("/")
        self.chat_url = f"{base}/chat/completions"

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        stream: bool,
        model: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.selection.ollama_tag,
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

    def _model_candidates(self) -> list[str]:
        candidates = [
            self.selection.ollama_tag,
            self.selection.model_id,
        ]
        unique: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in unique:
                unique.append(candidate)
        return unique

    @staticmethod
    def _parse_message(
        choice: dict[str, Any],
        *,
        usage: TokenUsage | None = None,
    ) -> LLMResponse:
        message = choice.get("message") or choice.get("delta") or {}
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        return LLMResponse(content=content, tool_calls=tool_calls, raw=choice, usage=usage)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        with httpx.Client(timeout=self.timeout) as client:
            for model in self._model_candidates():
                payload = self._build_payload(
                    messages,
                    tools=tools,
                    stream=False,
                    model=model,
                )
                try:
                    response = client.post(self.chat_url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    self.selection.ollama_tag = model
                    usage = TokenUsage.from_provider(data.get("usage"), model=model)
                    return self._parse_message(data["choices"][0], usage=usage)
                except Exception as exc:
                    err = classify_request_error(
                        exc,
                        model=model,
                        url=self.chat_url,
                    )
                    if isinstance(err, LLMModelNotFoundError) and model != self._model_candidates()[-1]:
                        continue
                    raise err from exc

        raise LLMModelNotFoundError(self.selection.ollama_tag)

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamToken | LLMResponse]:
        """
        Emite StreamToken por cada fragmento de texto y termina con LLMResponse completo.
        """
        with httpx.Client(timeout=self.timeout) as client:
            for model in self._model_candidates():
                content_parts: list[str] = []
                tool_calls_acc: dict[int, dict[str, Any]] = {}
                usage: TokenUsage | None = None
                emitted_tokens = False
                payload = self._build_payload(
                    messages,
                    tools=tools,
                    stream=True,
                    model=model,
                )

                try:
                    with client.stream("POST", self.chat_url, json=payload) as response:
                        if getattr(response, "is_error", False):
                            response.read()
                        response.raise_for_status()
                        self.selection.ollama_tag = model
                        for line in response.iter_lines():
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
                                chunk.get("usage"),
                                model=model,
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
                                idx = tc.get("index", 0)
                                entry = tool_calls_acc.setdefault(
                                    idx,
                                    {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    },
                                )
                                if tc.get("id"):
                                    entry["id"] = tc["id"]
                                fn = tc.get("function") or {}
                                if fn.get("name"):
                                    entry["function"]["name"] = fn["name"]
                                if fn.get("arguments"):
                                    entry["function"]["arguments"] += fn["arguments"]
                except Exception as exc:
                    err = classify_request_error(exc, model=model, url=self.chat_url)
                    if (
                        isinstance(err, LLMModelNotFoundError)
                        and not emitted_tokens
                        and model != self._model_candidates()[-1]
                    ):
                        continue
                    raise err from exc

                tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
                yield LLMResponse(
                    content="".join(content_parts),
                    tool_calls=tool_calls,
                    raw={},
                    usage=usage,
                )
                return

        raise LLMModelNotFoundError(self.selection.ollama_tag)
