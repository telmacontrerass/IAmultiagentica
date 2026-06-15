"""Compatibility alias for harness policy helpers."""

from __future__ import annotations

import sys

from ci2lab.harness.security import policy as _implementation

sys.modules[__name__] = _implementation
