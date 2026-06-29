"""Safe arithmetic evaluator exposed as the ``calc`` tool.

Lets a model verify the numbers it writes (sums, products, fractions) instead
of computing them in its head. Arithmetic ONLY: numeric literals and the
operators ``+ - * / // % **`` with parentheses and unary ``+``/``-``. The
expression is parsed with :mod:`ast` and walked node by node, so names, calls,
attributes, subscripts, comprehensions — anything that could touch the shell,
filesystem, or network — are rejected. There is no ``eval``.
"""

from __future__ import annotations

import ast

# Cap exponent magnitude so an input like ``10**10**10`` can never hang the
# process. Normal exercise arithmetic never needs anything close to this.
_MAX_POW_EXPONENT = 1000

# Cap the source length so a pathological input can't blow up the parser.
_MAX_EXPRESSION_LEN = 2000


def _format(value: float | int) -> str:
    """Render a numeric result without spurious floating-point noise."""
    if isinstance(value, bool):  # bools are ints in Python; reject upstream
        raise ValueError("boolean values are not allowed")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.6g}"
    raise ValueError("non-numeric result")


def _eval(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numeric constants are allowed")
        return node.value
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand)
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise ValueError("unsupported unary operator")
    if isinstance(node, ast.BinOp):
        left = _eval(node.left)
        right = _eval(node.right)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            if right == 0:
                raise ValueError("division by zero")
            return left / right
        if isinstance(op, ast.FloorDiv):
            if right == 0:
                raise ValueError("division by zero")
            return left // right
        if isinstance(op, ast.Mod):
            if right == 0:
                raise ValueError("division by zero")
            return left % right
        if isinstance(op, ast.Pow):
            if abs(right) > _MAX_POW_EXPONENT:
                raise ValueError("exponent too large")
            return left**right
        raise ValueError("unsupported operator")
    raise ValueError("unsupported expression element")


def calc(expression: str) -> str:
    """Evaluate ``expression`` and return ``"<expression> = <value>"``.

    Never raises: malformed or disallowed input returns a ``[calc error: …]``
    string so the agent can read the message and correct itself.
    """
    expr = (expression or "").strip()
    if not expr:
        return "[calc error: empty expression]"
    if len(expr) > _MAX_EXPRESSION_LEN:
        return "[calc error: expression too long]"
    try:
        tree = ast.parse(expr, mode="eval")
        result = _eval(tree)
        return f"{expr} = {_format(result)}"
    except SyntaxError:
        return "[calc error: could not parse expression — arithmetic only]"
    except ZeroDivisionError:
        return "[calc error: division by zero]"
    except ValueError as exc:
        return f"[calc error: {exc}]"
    except Exception as exc:  # defensive: never crash the loop
        return f"[calc error: {exc}]"
