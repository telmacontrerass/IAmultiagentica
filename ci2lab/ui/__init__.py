"""Local web UI — HTTP server on 127.0.0.1; shares pipeline and harness with CLI."""

from ci2lab.ui.server import run_ui

__all__ = ["run_ui"]
