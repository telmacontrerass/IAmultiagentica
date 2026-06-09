"""Cliente HTTP OpenAI-compatible (Ollama / vLLM)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import classify_request_error


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict[str, Any]]
    raw: dict[str, Any] = field(default_factory=dict)


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
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.selection.ollama_tag,
            "messages": messages,
            "temperature": self.selection.temperature,
            "max_tokens": self.selection.max_tokens,
            "stream": stream,
        }
        if tools and self.selection.supports_tools and self.selection.tool_mode == "native":
            payload["tools"] = tools
        return payload

    @staticmethod
    def _parse_message(choice: dict[str, Any]) -> LLMResponse:
        message = choice.get("message") or choice.get("delta") or {}
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        return LLMResponse(content=content, tool_calls=tool_calls, raw=choice)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        payload = self._build_payload(messages, tools=tools, stream=False)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(self.chat_url, json=payload)
                response.raise_for_status()
                data = response.json()
            return self._parse_message(data["choices"][0])
        except Exception as exc:
            raise classify_request_error(
                exc, model=self.selection.ollama_tag, url=self.chat_url
            ) from exc

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamToken | LLMResponse]:
        """
        Emite StreamToken por cada fragmento de texto y termina con LLMResponse completo.
        """
        payload = self._build_payload(messages, tools=tools, stream=True)
        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict[str, Any]] = {}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream("POST", self.chat_url, json=payload) as response:
                    response.raise_for_status()
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
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        if delta.get("content"):
                            piece = delta["content"]
                            content_parts.append(piece)
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
            raise classify_request_error(
                exc, model=self.selection.ollama_tag, url=self.chat_url
            ) from exc

        tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
        yield LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            raw={},
        )
