"""Tool capability categories are the single source of truth and stay coherent."""

from __future__ import annotations

from ci2lab.harness.tools.capabilities import (
    FILE_WRITE_TOOLS,
    MUTATING_TOOLS,
    READ_ONLY_TOOLS,
)
from ci2lab.harness.tools.schemas_parts.registry import TOOL_NAMES


def test_every_categorized_tool_is_a_real_tool():
    # The module's own self-check guards this at import; assert it here too so a
    # rename is caught as a test failure with a clear message.
    unknown = (READ_ONLY_TOOLS | MUTATING_TOOLS) - TOOL_NAMES
    assert not unknown, f"unknown tools in capability sets: {sorted(unknown)}"


def test_file_writes_are_a_subset_of_mutations():
    # Anything that writes a file necessarily mutates the workspace.
    assert FILE_WRITE_TOOLS <= MUTATING_TOOLS


def test_reads_and_mutations_are_disjoint():
    assert not (READ_ONLY_TOOLS & MUTATING_TOOLS)


def test_loop_uses_the_shared_categories():
    # The loop must not keep its own private copies — they would drift.
    from ci2lab.harness.query import loop

    assert loop.READ_ONLY_TOOLS is READ_ONLY_TOOLS
    assert loop.MUTATING_TOOLS is MUTATING_TOOLS
    assert loop.FILE_WRITE_TOOLS is FILE_WRITE_TOOLS


def test_coder_role_allowlist_is_recognized_as_write_capable():
    # The multi-agent edit allow-list and the loop's write-intent gate must agree
    # on what counts as a file write, so a coder is always seen as able to write.
    from ci2lab.harness.multiagent.roles import EDIT_TOOLS, READ_TOOLS

    assert FILE_WRITE_TOOLS <= EDIT_TOOLS
    assert not (FILE_WRITE_TOOLS & READ_TOOLS)
    # READ_TOOLS is the narrow role permission base, not the loop cache set.
    assert "web_fetch" not in READ_TOOLS
