#!/usr/bin/env python3
"""Deterministic audit wrapper for ci2lab_guard."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    legacy_name = "audit_" + "claude" + "_deterministic.py"
    runpy.run_path(str(Path(__file__).with_name(legacy_name)), run_name="__main__")
