"""Terminal line input with paste and multi-line support (Windows-friendly)."""

from __future__ import annotations

import sys


def read_prompt_line(prompt: str = "Tú> ") -> str:
    """
    Read one user message from the terminal.

    Uses prompt_toolkit when available so Ctrl+V / Shift+Insert paste works on
    Windows and pasted blocks can span multiple lines. Enter submits; Alt+Enter
    inserts a newline.
    """
    if not sys.stdin.isatty():
        return _fallback_input(prompt)

    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
    except ImportError:
        return _fallback_input(prompt)

    bindings = KeyBindings()

    @bindings.add("enter")
    def _submit(event) -> None:  # noqa: ANN001
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _newline(event) -> None:  # noqa: ANN001
        event.current_buffer.insert_text("\n")

    session = PromptSession(
        history=InMemoryHistory(),
        multiline=True,
        key_bindings=bindings,
        prompt_continuation=lambda *_args: "  ",
    )
    text = session.prompt(HTML(f"\n<b>{_escape_html(prompt)}</b> "))
    return text.strip()


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _fallback_input(prompt: str) -> str:
    print(f"\n{prompt}", end="", flush=True)  # noqa: T201
    try:
        return input().strip()  # noqa: T201
    except EOFError:
        raise
