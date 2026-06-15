"""Compatibility alias for harness permission helpers."""

from __future__ import annotations

import sys

from ci2lab.harness.security import permissions as _implementation

sys.modules[__name__] = _implementation
