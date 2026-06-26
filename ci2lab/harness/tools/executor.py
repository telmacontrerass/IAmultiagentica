"""Execute normalized tool calls.

This module is the public entry point for the tool-execution pipeline. It
re-exports the orchestration helpers implemented in
:mod:`ci2lab.harness.tools.executor_parts` so callers can import them from a
single, stable location.
"""

from __future__ import annotations

from ci2lab.harness.security.permissions import check_permission
from ci2lab.harness.tools.executor_parts.arguments import (
    normalize_tool_arguments,
    parse_arguments,
)
from ci2lab.harness.tools.executor_parts.audit import (
    audit_security_decision as _audit_security_decision,
)
from ci2lab.harness.tools.executor_parts.audit import (
    ensure_audit_persist_context as _ensure_audit_persist_context,
)
from ci2lab.harness.tools.executor_parts.confirmation import (
    resolve_tool_confirm as _resolve_tool_confirm,
)
from ci2lab.harness.tools.executor_parts.core import execute_tool
from ci2lab.harness.tools.executor_parts.write_tools import (
    execute_write_tool as _execute_write_tool,
)

__all__ = [
    "check_permission",
    "execute_tool",
    "normalize_tool_arguments",
    "parse_arguments",
]
