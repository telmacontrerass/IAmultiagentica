"""OpenAI function schemas for runtime tools.

Defines :data:`RUNTIME_SCHEMAS`, the schemas for tools that execute commands in
the workspace (currently ``bash``). These are aggregated into the full tool set
by :mod:`ci2lab.harness.tools.schemas_parts.builtins`.
"""

from __future__ import annotations

from typing import Any

#: OpenAI-compatible function schemas for runtime/execution tools.
RUNTIME_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command (build, tests, installs, running scripts). Asks for confirmation. Prefer read-only tools for exploring; use bash only when no read-only tool fits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calc",
            "description": (
                "Evaluate an arithmetic expression exactly and return its value. "
                "Use this to verify any sum, product, or fraction before you write "
                "it down -- do not compute multi-term arithmetic in your head. "
                "Arithmetic only: numbers and + - * / // % ** with parentheses and "
                "unary minus, e.g. '8*(-393520) + 9*(-241820) - (-249910)' or "
                "'298 + 5074630 / (8*58.4 + 9*47.15 + 47*34.9)'. No variables or functions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic expression to evaluate exactly.",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "symcalc",
            "description": (
                "Evaluate a symbolic / matrix expression exactly with a computer "
                "algebra system (SymPy). Use this for anything beyond scalar "
                "arithmetic: matrix row reduction, determinants, kernels, "
                "eigenvalues, Jordan form, dot products, and exact radicals or "
                "fractions. Examples: "
                "'Matrix([[1,1,0],[1,-1,6]]).rref()', "
                "'Matrix([[1,1,0],[1,-1,6]]).nullspace()', "
                "'Matrix([[2,0,0,1],[0,2,0,0],[0,0,3,1],[0,0,-1,1]]).jordan_form()[1]', "
                "'sqrt(24)', 'Matrix([1,0,2,1]).dot(Matrix([1,-1,1,0]))'. "
                "Matrices use SymPy syntax: Matrix([[row1],[row2],...]). "
                "Arithmetic only — no imports, variables, or arbitrary code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "SymPy/matrix expression to evaluate exactly.",
                    },
                },
                "required": ["expression"],
            },
        },
    },
]
