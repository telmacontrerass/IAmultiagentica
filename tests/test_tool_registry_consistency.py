"""Cross-registry consistency for built-in tools.

A built-in tool is declared in several places that must agree:

* ``TOOL_NAMES`` — the canonical name set (``is_known_tool`` gate),
* ``DISPATCH`` — name -> implementation,
* ``FUNCTION_SCHEMAS`` — the JSON schema advertised to the model,
* ``NAME_MAP`` — synonym aliases that normalise to a canonical name,
* the capability sets in ``capabilities`` (read-only / file-write / mutating).

These tests fail fast if any of those drift apart — e.g. a tool advertised to
the model with no implementation, or a dispatch entry the model can never reach
because the name is not recognised.
"""

from __future__ import annotations

from ci2lab.harness.parsing_parts.common import NAME_MAP
from ci2lab.harness.tools.capabilities import (
    FILE_WRITE_TOOLS,
    MUTATING_TOOLS,
    READ_ONLY_TOOLS,
)
from ci2lab.harness.tools.dispatch import DISPATCH
from ci2lab.harness.tools.schemas_parts.builtins import FUNCTION_SCHEMAS
from ci2lab.harness.tools.schemas_parts.registry import TOOL_NAMES

_SCHEMA_NAMES = frozenset(schema["function"]["name"] for schema in FUNCTION_SCHEMAS)


def test_every_dispatch_entry_is_a_known_tool():
    # A dispatch entry the executor can never reach (because is_known_tool
    # rejects the name) is dead code or, worse, an advertised-but-broken tool.
    assert set(DISPATCH) <= TOOL_NAMES, sorted(set(DISPATCH) - TOOL_NAMES)


def test_every_known_tool_has_a_dispatch_entry():
    assert set(DISPATCH) >= TOOL_NAMES, sorted(TOOL_NAMES - set(DISPATCH))


def test_every_advertised_schema_maps_to_a_known_tool():
    # Anything the model is told it can call must be recognised and runnable.
    assert _SCHEMA_NAMES <= TOOL_NAMES, sorted(_SCHEMA_NAMES - TOOL_NAMES)
    assert set(DISPATCH) >= _SCHEMA_NAMES, sorted(_SCHEMA_NAMES - set(DISPATCH))


def test_name_map_targets_are_known_tools():
    targets = set(NAME_MAP.values())
    assert targets <= TOOL_NAMES, sorted(targets - TOOL_NAMES)


def test_capability_sets_reference_known_tools():
    caps = READ_ONLY_TOOLS | FILE_WRITE_TOOLS | MUTATING_TOOLS
    assert caps <= TOOL_NAMES, sorted(caps - TOOL_NAMES)


def test_file_write_tools_are_a_subset_of_mutating_tools():
    assert FILE_WRITE_TOOLS <= MUTATING_TOOLS


def test_read_and_write_categories_are_disjoint():
    assert not (READ_ONLY_TOOLS & MUTATING_TOOLS)
