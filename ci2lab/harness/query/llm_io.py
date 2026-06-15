"""LLM call helpers (streaming and non-streaming)."""

from __future__ import annotations

from typing import Any

from rich.live import Live
from rich.text import Text

from ci2lab.console import console
from ci2lab.harness.llm_client import LLMClient, LLMResponse, StreamToken


def call_llm(
    client: LLMClient,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    stream: bool,
) -> LLMResponse:
    if not stream:
        return client.chat(messages, tools=tools)

    llm_response: LLMResponse | None = None
    buffer = Text()

    with Live(buffer, console=console, refresh_per_second=12, transient=False) as live:
        for event in client.stream_chat(messages, tools=tools):
            if isinstance(event, StreamToken):
                buffer.append(event.text)
                live.update(buffer)
            else:
                llm_response = event

    if llm_response is None:
        return LLMResponse(content=buffer.plain, tool_calls=[], raw={})
    if not llm_response.content and buffer.plain:
        llm_response = LLMResponse(
            content=buffer.plain,
            tool_calls=llm_response.tool_calls,
            raw=llm_response.raw,
        )
    return llm_response
