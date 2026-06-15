"""Tests for terminal input helpers."""

from __future__ import annotations

from ci2lab.harness import terminal_input


def test_escape_html() -> None:
    assert terminal_input._escape_html("a<b>&c") == "a&lt;b&gt;&amp;c"


def test_fallback_input(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda: "  pasted text  ")
    assert terminal_input._fallback_input("> ") == "pasted text"
