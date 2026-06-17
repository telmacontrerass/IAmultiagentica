"""Error-class retry governor.

Bounds repeated tool failures so the loop does not spend its whole round budget
retrying the same broken call. It complements the signature-based loop detector:

- The signature detector catches a tool repeated with *identical* arguments.
- The governor catches the same tool failing with the same *error class* even
  when the arguments vary slightly each round (e.g. `docx_to_pdf` failing with
  "no PDF engine" for several different output paths).

Two limits:

- MAX_SAME_CALL: how many times the exact same call may really run before it is
  short-circuited (no execution) with a "try a different approach" result.
- ERROR_CLASS_LIMIT: how many times one tool may fail with the same error class
  (across any arguments) before the run stops with a blocker summary.
"""

from __future__ import annotations

from ci2lab.harness.security.policy import tool_call_signature
from ci2lab.harness.types import ToolCall, ToolResult

MAX_SAME_CALL = 2
ERROR_CLASS_LIMIT = 3

# (error class, substrings that identify it in tool output). Order matters:
# the first match wins, so put the specific classes before the generic ones.
_ERROR_CLASS_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("not_allowed_by_skill", ("not allowed by the active skill",)),
    ("path_outside", ("outside the workspace", "outside the project", "path outside")),
    (
        "blocked_by_policy",
        ("blocked by workspace policy", "blocked by security policy",
         "policy_secret_file_blocked", "command blocked by security policy"),
    ),
    (
        "source_not_found",
        ("file does not exist", "source file not found", "not a directory",
         "no such file"),
    ),
    (
        "invalid_source",
        ("is not a valid .docx", "is corrupt", "could not parse", "couldn't parse",
         "no extractable text", "not a valid word document"),
    ),
    ("no_pdf_engine", ("valid pdf engine is missing", "no conversion engine available")),
    (
        "edit_mismatch",
        ("old_string not found", "old_string and new_string are identical",
         "patch context not found", "old_string appears"),
    ),
)


def normalize_error_class(result: ToolResult) -> str:
    """Map a tool result to a small, stable error-class label."""
    if not result.is_error:
        return "none"
    outcome = (result.outcome or "").lower()
    if outcome == "blocked_by_skill":
        return "not_allowed_by_skill"
    if outcome in {"blocked_by_policy", "blocked_by_workspace", "blocked_by_secret_policy"}:
        return "blocked_by_policy"
    content = result.content.lower()
    for label, needles in _ERROR_CLASS_RULES:
        if any(needle in content for needle in needles):
            return label
    return "tool_error"


def tool_error_signature(call: ToolCall, result: ToolResult) -> str:
    """Signature combining the exact call and its error class."""
    return f"{tool_call_signature(call)}::{normalize_error_class(result)}"


def error_class_key(call: ToolCall, result: ToolResult) -> str:
    """Coarse key (tool + error class) ignoring arguments."""
    return f"{call.name}::{normalize_error_class(result)}"
