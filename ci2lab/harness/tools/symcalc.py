"""Symbolic / matrix calculator exposed as the ``symcalc`` tool.

Where ``calc`` handles scalar arithmetic, ``symcalc`` handles the operations an
algebra exercise actually needs: matrix row reduction, determinants, kernels,
eigenvalues/Jordan form, dot products, and exact radicals/fractions. It is
backed by SymPy.

Safety: the expression is parsed with :mod:`ast` and rejected unless every node
is on an allow-list. Method/attribute access to dunders (``__class__`` etc.) is
forbidden, names must resolve to a curated SymPy namespace, and evaluation runs
with no builtins. It is not a general Python sandbox — it targets CAS one-liners
like ``Matrix([[1,1,0],[1,-1,6]]).rref()``.
"""

from __future__ import annotations

import ast

_MAX_EXPRESSION_LEN = 4000

# AST node types permitted anywhere in the expression.
_ALLOWED_NODES = (
    ast.Expression,
    ast.Call,
    ast.Attribute,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Subscript,
    ast.Slice,
    ast.keyword,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.MatMult,
    ast.USub,
    ast.UAdd,
)


def _build_namespace() -> dict:
    """Return the curated SymPy names the expression may reference."""
    import sympy as sp

    names = [
        "Matrix",
        "ImmutableMatrix",
        "eye",
        "zeros",
        "ones",
        "diag",
        "Rational",
        "Integer",
        "Float",
        "sqrt",
        "Abs",
        "sign",
        "simplify",
        "expand",
        "factor",
        "nsimplify",
        "together",
        "cancel",
        "symbols",
        "Symbol",
        "S",
        "I",
        "pi",
        "E",
        "oo",
        "GramSchmidt",
        "Transpose",
        "transpose",
        "trace",
        "det",
        "gcd",
        "lcm",
    ]
    ns: dict = {}
    for n in names:
        obj = getattr(sp, n, None)
        if obj is not None:
            ns[n] = obj
    return ns


def _validate(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"unsupported syntax: {type(node).__name__}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("access to private/dunder attributes is not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("private/dunder names are not allowed")


def symcalc(expression: str) -> str:
    """Evaluate a SymPy/matrix expression and return ``"<expr> = <value>"``.

    Never raises: bad or disallowed input returns a ``[symcalc error: …]``
    string so the agent can read the message and correct itself.
    """
    expr = (expression or "").strip()
    if not expr:
        return "[symcalc error: empty expression]"
    if len(expr) > _MAX_EXPRESSION_LEN:
        return "[symcalc error: expression too long]"
    try:
        import sympy  # noqa: F401 - ensures a clear error if missing
    except ImportError:
        return "[symcalc error: sympy is not installed — run: pip install sympy]"
    try:
        tree = ast.parse(expr, mode="eval")
        _validate(tree)
        namespace = _build_namespace()
        # Sandboxed eval: AST-allow-listed above, no builtins, curated namespace.
        result = eval(
            compile(tree, "<symcalc>", "eval"),
            {"__builtins__": {}},
            namespace,
        )
        return f"{expr} = {result}"
    except SyntaxError:
        return "[symcalc error: could not parse expression]"
    except ValueError as exc:
        return f"[symcalc error: {exc}]"
    except Exception as exc:  # defensive: never crash the loop
        return f"[symcalc error: {type(exc).__name__}: {exc}]"
