"""Consola Rich compartida por CLI, arnés, evals y UI.

Única instancia para toda la aplicación: la salida es coherente y los tests
pueden silenciarla con un solo patch (`ci2lab.console.console.print`).
"""

from __future__ import annotations

from rich.console import Console

console = Console()
