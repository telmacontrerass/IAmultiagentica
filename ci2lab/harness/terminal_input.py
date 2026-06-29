"""Terminal line input with paste and multi-line support (Windows-friendly)."""

from __future__ import annotations

import sys
from typing import Any


def read_prompt_line(prompt: str = "You> ") -> str:
    """
    Read one user message from the terminal.

    Uses prompt_toolkit when available so Ctrl+V / Shift+Insert paste works on
    Windows and pasted blocks can span multiple lines. Enter submits; Alt+Enter
    inserts a newline.

    Args:
        prompt: The prompt label shown before the input field.

    Returns:
        The entered message, stripped of surrounding whitespace.
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
    def _submit(event: Any) -> None:
        """Submit the current buffer when Enter is pressed."""
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _newline(event: Any) -> None:
        """Insert a literal newline when Alt+Enter is pressed."""
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
    """Escape ``&``, ``<`` and ``>`` so ``text`` is safe in prompt_toolkit HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fallback_input(prompt: str) -> str:
    """Read a line via the builtin ``input`` when prompt_toolkit is unavailable.

    Args:
        prompt: The prompt label to print before reading.

    Returns:
        The entered line, stripped of surrounding whitespace.

    Raises:
        EOFError: If end-of-file is reached before any input.
    """
    print(f"\n{prompt}", end="", flush=True)
    try:
        return input().strip()
    except EOFError:
        raise
