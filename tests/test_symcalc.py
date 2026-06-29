"""Tests for the symbolic / matrix `symcalc` tool."""

from __future__ import annotations

from ci2lab.harness.tools.dispatch import DISPATCH
from ci2lab.harness.tools.schemas_parts.registry import TOOL_NAMES
from ci2lab.harness.tools.symcalc import symcalc


def test_rref():
    out = symcalc("Matrix([[1,1,0],[1,-1,6],[1,1,0],[1,-1,6]]).rref()")
    # Reduced row-echelon plus pivot columns (0, 1).
    assert "(0, 1)" in out
    assert "[1, 0," in out and "[0, 1," in out


def test_nullspace():
    out = symcalc("Matrix([[1,1,0],[1,-1,6],[1,1,0],[1,-1,6]]).nullspace()")
    assert "-3" in out and "3" in out and "1" in out


def test_eigenvalue_multiplicity():
    out = symcalc("Matrix([[2,0,0,1],[0,2,0,0],[0,0,3,1],[0,0,-1,1]]).eigenvals()")
    assert out.endswith("{2: 4}")


def test_jordan_form():
    out = symcalc("Matrix([[2,0,0,1],[0,2,0,0],[0,0,3,1],[0,0,-1,1]]).jordan_form()[1]")
    # A 3x3 Jordan block for eigenvalue 2 plus a 1x1 block.
    assert "2, 1, 0, 0" in out and "0, 0, 0, 2" in out


def test_exact_radical():
    assert symcalc("sqrt(24)") == "sqrt(24) = 2*sqrt(6)"


def test_dot_product():
    assert symcalc("Matrix([1,0,2,1]).dot(Matrix([1,-1,1,0]))").endswith("= 3")


def test_dunder_name_rejected():
    assert symcalc("__import__('os')").startswith("[symcalc error")


def test_dunder_attribute_rejected():
    assert symcalc("(1).__class__").startswith("[symcalc error")


def test_builtin_not_available():
    assert symcalc("open('x')").startswith("[symcalc error")


def test_empty_expression():
    assert symcalc("   ").startswith("[symcalc error")


def test_registered_and_dispatchable():
    assert "symcalc" in TOOL_NAMES
    assert "symcalc" in DISPATCH
    assert DISPATCH["symcalc"](None, {"expression": "Matrix([[1,2],[3,4]]).det()"}).endswith("= -2")
