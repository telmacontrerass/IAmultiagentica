"""Rich console shared by the CLI, harness, evals and UI.

Single instance for the whole application: output stays consistent and tests
can silence it with a single patch (`ci2lab.console.console.print`).
"""

from __future__ import annotations

from rich.console import Console

console = Console()
