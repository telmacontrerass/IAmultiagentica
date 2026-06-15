"""Compatibility alias for context compaction."""

from __future__ import annotations

import sys

from ci2lab.harness.context import compact as _implementation

sys.modules[__name__] = _implementation
