"""Compatibility alias for the refactored query loop."""

from __future__ import annotations

import sys

from ci2lab.harness.query import loop as _implementation

sys.modules[__name__] = _implementation
