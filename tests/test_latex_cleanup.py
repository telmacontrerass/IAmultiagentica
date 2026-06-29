"""Tests for the deterministic LaTeX -> plain-text cleanup on the .md export."""

from __future__ import annotations

from ci2lab.harness.repl import _latex_to_plaintext as clean


def test_chemical_formula_subscripts():
    src = r"\text{C}_8\text{H}_{18} \rightarrow 8\text{CO}_2 + 9\text{H}_2\text{O} + 47\text{N}_2"
    assert clean(src) == "C8H18 → 8CO2 + 9H2O + 47N2"


def test_fraction_and_times():
    src = r"T = 298 + \frac{-5074630}{8 \times 58.4} = 2302.32 \, \text{K}"
    assert clean(src) == "T = 298 + (-5074630)/(8 × 58.4) = 2302.32 K"


def test_degree_celsius_and_thin_space():
    assert clean(r"2029.32 \, ^\circ\text{C}") == "2029.32 °C"


def test_inline_math_delimiters_removed():
    assert "\\(" not in clean(r"\( T = 5 \)")
    assert "\\[" not in clean(r"\[ T = 5 \]")


def test_snake_case_words_are_not_mangled():
    # `_` followed by a letter (snake_case) must survive; only `_<digit>` is a subscript.
    src = "affects_result: no, likely_source: transcription, used_later: yes"
    assert clean(src) == src


def test_no_backslash_commands_left():
    out = clean(r"\left[ 8\text{CO}_2 \right] \quad \rightarrow \quad X")
    assert "\\" not in out
