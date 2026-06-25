"""HTTP client for Ollama (native API) and OpenAI-compatible backends.

For Ollama we talk to the **native** `/api/chat` endpoint, not the
OpenAI-compatible `/v1/chat/completions` one. Only the native endpoint honors
`options.num_ctx` — the context window the model actually loads. The `/v1`
endpoint silently ignores it and falls back to Ollama's small server default
(~4k tokens), so on a longer task the model would lose the system prompt and
earlier turns even though the harness budgeted for the full window (that
mismatch shows up as the agent "forgetting" earlier steps and looping). Sending
`num_ctx = context_length` keeps the real window and the harness's compaction
math in agreement. Non-Ollama backends (e.g. vLLM) keep the OpenAI path.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import (
    LLMCancelledError,
    LLMModelNotFoundError,
    classify_request_error,
)
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
        base = selection.backend_url.rstrip("/")
        self.chat_url = f"{base}/chat/completions"
        # Native Ollama endpoint lives at the server root, not under /v1.
        native_base = base[:-3].rstrip("/") if base.endswith("/v1") else base
        self.ollama_chat_url = f"{native_base}/api/chat"

    def _use_native(self) -> bool:
        return self.selection.backend == "ollama"

    def _num_ctx(self) -> int:
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

    def _build_native_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        stream: bool,
        model: str | None = None,
    ) -> dict[str, Any]:
        # `num_ctx` is the whole point of using the native endpoint: it makes the
        # model load the context window the harness assumes it has.
        options: dict[str, Any] = {"temperature": self.selection.temperature}
        num_ctx = self._num_ctx()
        if num_ctx > 0:
            options["num_ctx"] = num_ctx
        if self.selection.max_tokens:
            options["num_predict"] = self.selection.max_tokens
        payload: dict[str, Any] = {
            "model": model or self.selection.ollama_tag,
            "messages": self._to_native_messages(messages),
            "stream": stream,
            "options": options,
        }
        if tools and self.selection.supports_tools and self.selection.tool_mode == "native":
            payload["tools"] = tools
        return payload

    @staticmethod
    def _to_native_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Adapt the harness's OpenAI-shaped history to Ollama's native format.

        History is stored OpenAI-style (for the /v1 path and session files):
        tool-call `arguments` are a JSON *string* and tool results carry a
        `tool_call_id`. Ollama's native /api/chat instead wants `arguments` as a
        JSON *object* and a bare `{role: tool, content}` — sending the OpenAI
        shape makes it reject the request once a prior tool call is replayed.

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
                # Multimodal message: OpenAI list-of-blocks → Ollama native format.
                # Collect text parts and base64 image data separately.
                text_parts: list[str] = []
                images: list[str] = []
                for block in msg["content"]:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text") or "")
                    elif block.get("type") == "image_url":
                        url = (block.get("image_url") or {}).get("url", "")
                        # Strip "data:image/TYPE;base64," prefix → raw base64.
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

    def _model_candidates(self) -> list[str]:
        # Prefer concrete runtime tags (e.g. "phi4:14b"). Catalog ids are
        # often slugified ("phi4-14b") and are not valid Ollama model names.
        candidates = [self.selection.ollama_tag]
        model_id = (self.selection.model_id or "").strip()
        if (
            model_id
            and model_id != self.selection.ollama_tag
            and ":" in model_id
        ):
            candidates.append(model_id)
        unique: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in unique:
                unique.append(candidate)
        return unique

    @staticmethod
    def _raise_if_cancelled(cancel_event: Any | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise LLMCancelledError()

    @staticmethod
    def _watch_cancellation(
        client: httpx.Client,
        cancel_event: Any | None,
    ) -> threading.Event | None:
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

    @staticmethod
    def _parse_native(data: dict[str, Any], *, model: str) -> LLMResponse:
        message = data.get("message") or {}
        content = message.get("content") or ""
        # Native tool_calls carry `function.arguments` as an object; the
        # downstream parser (`native_to_tool_calls`) already accepts that shape.
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
        native = self._use_native()
        url = self.ollama_chat_url if native else self.chat_url
        with httpx.Client(timeout=self.timeout) as client:
            done = self._watch_cancellation(client, cancel_event)
            try:
                for model in self._model_candidates():
                    self._raise_if_cancelled(cancel_event)
                    payload = (
                        self._build_native_payload(
                            messages, tools=tools, stream=False, model=model
                        )
                        if native
                        else self._build_payload(
                            messages, tools=tools, stream=False, model=model
                        )
                    )
                    try:
                        response = client.post(url, json=payload)
                        response.raise_for_status()
                        data = response.json()
                        self.selection.ollama_tag = model
                        if native:
                            return self._parse_native(data, model=model)
                        usage = TokenUsage.from_provider(data.get("usage"), model=model)
                        return self._parse_message(data["choices"][0], usage=usage)
                    except Exception as exc:
                        self._raise_if_cancelled(cancel_event)
                        err = classify_request_error(
                            exc,
                            model=model,
                            url=url,
                            num_images=self.vision_image_count,
                        )
                        if isinstance(err, LLMModelNotFoundError) and model != self._model_candidates()[-1]:
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
        """
        Emits a StreamToken for each text fragment and ends with a complete LLMResponse.
        """
        if self._use_native():
            yield from self._stream_native(messages, tools=tools, cancel_event=cancel_event)
        else:
            yield from self._stream_openai(messages, tools=tools, cancel_event=cancel_event)

    def _stream_native(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any | None = None,
    ) -> Iterator[StreamToken | LLMResponse]:
        with httpx.Client(timeout=self.timeout) as client:
            done = self._watch_cancellation(client, cancel_event)
            try:
                for model in self._model_candidates():
                    self._raise_if_cancelled(cancel_event)
                    content_parts: list[str] = []
                    tool_calls_acc: list[dict[str, Any]] = []
                    usage: TokenUsage | None = None
                    emitted_tokens = False
                    payload = self._build_native_payload(
                        messages, tools=tools, stream=True, model=model
                    )

                    try:
                        with client.stream("POST", self.ollama_chat_url, json=payload) as response:
                            if getattr(response, "is_error", False):
                                response.read()
                            response.raise_for_status()
                            self.selection.ollama_tag = model
                            # Native streaming is newline-delimited JSON objects, not
                            # SSE `data:` frames.
                            for line in response.iter_lines():
                                self._raise_if_cancelled(cancel_event)
                                if not line:
                                    continue
                                text = line.strip()
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
                                # Ollama emits each tool call whole (no OpenAI-style
                                # per-fragment deltas), so just collect them.
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
                            url=self.ollama_chat_url,
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

    def _stream_openai(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any | None = None,
    ) -> Iterator[StreamToken | LLMResponse]:
        with httpx.Client(timeout=self.timeout) as client:
            done = self._watch_cancellation(client, cancel_event)
            try:
                for model in self._model_candidates():
                    self._raise_if_cancelled(cancel_event)
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
