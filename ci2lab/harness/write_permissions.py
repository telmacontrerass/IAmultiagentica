"""Compatibility alias for supervised write permissions."""

from __future__ import annotations

import sys

from ci2lab.harness.security import write_permissions as _implementation

sys.modules[__name__] = _implementation
