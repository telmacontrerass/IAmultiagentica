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
    cancel_event: Any | None = None,
) -> LLMResponse:
    """Call the LLM, optionally rendering streamed tokens to the console.

    Args:
        client: The LLM client used to issue the chat request.
        messages: The conversation history to send, as chat message dicts.
        tools: Tool schemas to expose to the model, or ``None`` for no tools.
        stream: When ``True``, stream tokens live; otherwise make a single
            blocking call.
        cancel_event: Optional cancellation primitive forwarded to the client
            to abort an in-flight request.

    Returns:
        The model's response. In streaming mode, the streamed text is folded
        back into the response when the final event carries no content.
    """
    if not stream:
        if cancel_event is None:
            return client.chat(messages, tools=tools)
        return client.chat(messages, tools=tools, cancel_event=cancel_event)

    llm_response: LLMResponse | None = None
    buffer = Text()

    with Live(buffer, console=console, refresh_per_second=12, transient=False) as live:
        events = (
            client.stream_chat(messages, tools=tools)
            if cancel_event is None
            else client.stream_chat(messages, tools=tools, cancel_event=cancel_event)
        )
        for event in events:
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
            usage=llm_response.usage,
        )
    return llm_response
