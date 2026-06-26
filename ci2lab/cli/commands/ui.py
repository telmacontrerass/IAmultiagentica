"""ui command."""

from __future__ import annotations

import argparse

from ci2lab.config import Ci2LabConfig


def _cmd_ui(args: argparse.Namespace, runtime: Ci2LabConfig) -> int:
    """Launch the local web interface.

    Args:
        args: Parsed CLI arguments (``--host``, ``--port`` and ``--no-open``).
        runtime: The merged runtime configuration passed through to the server.

    Returns:
        Process exit code returned by the UI server.
    """
    from ci2lab.ui import run_ui

    return run_ui(
        runtime,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
    )
