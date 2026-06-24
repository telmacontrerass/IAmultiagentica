"""Rich console shared by the CLI, harness, evals and UI.

Single instance for the whole application: output stays consistent and tests
can silence it with a single patch (`ci2lab.console.console.print`).
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator

from rich.console import Console

console = Console()


class _ActiveProgress:
    """Track the live status spinner so interactive prompts can pause it.

    The transient "thinking" spinner is a Rich live display backed by a
    background refresh thread. While it runs it keeps repainting the bottom
    terminal line, which clobbers any ``input()`` prompt rendered underneath —
    e.g. a permission request would stay hidden and the user could never answer
    it. Whatever owns the spinner registers it here; code about to read user
    input wraps that read in :meth:`suspended` so the spinner stops first and
    resumes afterwards.
    """

    def __init__(self) -> None:
        self._status: Any = None

    def set(self, status: Any) -> None:
        self._status = status

    def clear(self, status: Any = None) -> None:
        if status is None or self._status is status:
            self._status = None

    @contextlib.contextmanager
    def suspended(self) -> Iterator[None]:
        status = self._status
        if status is not None:
            status.stop()
        try:
            yield
        finally:
            # Only resume if the same spinner is still the active one; it may
            # have been cleared or replaced while input was being read.
            if status is not None and self._status is status:
                status.start()


active_progress = _ActiveProgress()
