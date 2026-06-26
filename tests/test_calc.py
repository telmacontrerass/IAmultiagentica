"""Tests for the safe arithmetic `calc` tool."""

from __future__ import annotations

from ci2lab.harness.tools.calc import calc
from ci2lab.harness.tools.dispatch import DISPATCH
from ci2lab.harness.tools.schemas_parts.registry import TOOL_NAMES


def test_enthalpy_sum_with_negative_terms():
    # The exact line phi4 kept rendering inconsistently.
    assert calc("8*(-393520) + 9*(-241820) - (-249910)").endswith("= -5074630")


def test_double_negation_gives_the_wrong_number():
    # Confirms the tool exposes the difference between the right and wrong forms.
    assert calc("-8*(-393520) - 9*(-241820) + 249910").endswith("= 5574450")


def test_fraction_formats_without_float_noise():
    result = calc("298 + 5074630 / (8*58.4 + 9*47.15 + 47*34.9)")
    assert result.endswith("= 2302.32")


def test_integer_result_has_no_decimal_point():
    assert calc("2 + 2") == "2 + 2 = 4"


def test_division_by_zero_is_reported_not_raised():
    assert "division by zero" in calc("1/0")


def test_names_are_rejected():
    out = calc("__import__('os').system('echo hi')")
    assert out.startswith("[calc error")


def test_attribute_and_call_rejected():
    assert calc("(1).bit_length()").startswith("[calc error")


def test_oversized_exponent_rejected():
    assert calc("10**100000").startswith("[calc error")


def test_empty_expression():
    assert calc("   ").startswith("[calc error")


def test_calc_is_registered_and_dispatchable():
    assert "calc" in TOOL_NAMES
    assert "calc" in DISPATCH
    assert DISPATCH["calc"](None, {"expression": "3*7"}) == "3*7 = 21"
