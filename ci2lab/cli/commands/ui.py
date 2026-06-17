"""ui command."""

from __future__ import annotations

import argparse

from ci2lab.config import Ci2LabConfig


def _cmd_ui(args: argparse.Namespace, runtime: Ci2LabConfig) -> int:
    from ci2lab.ui import run_ui

    return run_ui(
        runtime,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
    )
