"""Single source of truth for tool capability categories.

These sets classify the built-in tools by *what they do* — independent of how a
model names them and independent of which tools a given role/skill is *allowed*
to use (that is a permission concern, handled by allow-lists). Every consumer
imports from here so the categories can never drift apart:

- the ReAct loop's per-turn read cache and write-intent nudges
  (`ci2lab.harness.query.loop`),
- the multi-agent role allow-lists (`ci2lab.harness.multiagent.roles`),
- anything else that needs to reason about reads vs. writes vs. mutations.

Names are the canonical tool names from `TOOL_NAMES`; a module-level check fails
fast if any entry is misspelled or a tool is renamed without updating these
sets.
"""

from __future__ import annotations

from ci2lab.harness.tools.schemas_parts.registry import TOOL_NAMES

# Tools that only observe the workspace or the web. Their result for a given
# argument set is stable within a turn unless a mutating tool runs, so the loop
# may serve a repeat call from its per-turn cache instead of re-executing. Web
# lookups are included: re-issuing the same search/fetch returns essentially the
# same result and only burns rounds (weak models often repeat them).
READ_ONLY_TOOLS = frozenset({
    "calc",
    "read_file",
    "read_document",
    "ls",
    "tree",
    "glob",
    "grep",
    "file_info",
    "inspect_file",
    "git_status",
    "git_diff",
    "web_search",
    "web_fetch",
})

# Tools that create or edit FILE CONTENT directly. An agent whose effective
# allow-list contains none of these genuinely cannot author a file, so a
# write-oriented nudge ("you described a change but never wrote it") must stay
# silent for it. `bash` is deliberately excluded: a role with only `bash` is not
# meant to author files, and telling it to "call write_file" pushes it out of
# its lane.
FILE_WRITE_TOOLS = frozenset({
    "write_file",
    "edit_file",
    "apply_patch",
    "notebook_edit",
    "write_docx",
    "fill_docx_template",
})

# Everything that can change workspace state: file writers plus shell, document
# conversions, and an "edit"-mode `delegate` (its subagent can write files).
# Running any of these invalidates the read-only cache so a later re-read
# reflects the new state, and marks that a write was attempted this turn.
MUTATING_TOOLS = FILE_WRITE_TOOLS | frozenset({
    "bash",
    "docx_to_pdf",
    "pdf_to_docx",
    "delegate",
})

# Fail fast if a category references a tool that no longer exists: this keeps the
# categories honest when tools are renamed or removed.
_UNKNOWN = (READ_ONLY_TOOLS | MUTATING_TOOLS) - TOOL_NAMES
if _UNKNOWN:  # pragma: no cover - guards against developer error
    raise RuntimeError(
        f"tool capability sets reference unknown tools: {sorted(_UNKNOWN)}"
    )

__all__ = ["READ_ONLY_TOOLS", "FILE_WRITE_TOOLS", "MUTATING_TOOLS"]
