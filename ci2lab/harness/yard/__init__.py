"""Quarry-Yard salvage components exposed through a single gateway tool.

The Yard is a data-driven catalogue of reusable code components salvaged from
other projects. Unlike a skill (a markdown *playbook* the model reads), a Yard
component ships runnable Python: the gateway ``yard`` tool lists the catalogue,
describes one component's entrypoints on demand, and executes an entrypoint
server-side — returning only the result, never the source, so the per-turn tool
schema stays constant no matter how many components exist.

Each component lives in its own directory under :mod:`builtin` (or under a
workspace/user Yard root) as a ``COMPONENT.md`` manifest plus a ``core/``
folder of vendored modules. Dropping a new directory in is enough to register a
component — there is no per-component code to edit.

Public surface:

- :class:`~ci2lab.harness.yard.loader.YardComponent` /
  :class:`~ci2lab.harness.yard.loader.YardEntrypoint` — the data model.
- :func:`~ci2lab.harness.yard.loader.load_components` — discover components.
- :func:`~ci2lab.harness.yard.loader.format_yard_catalog` — render the catalogue.
- :func:`~ci2lab.harness.yard.runner.execute` — run one entrypoint.
"""

from __future__ import annotations

from ci2lab.harness.yard.loader import (
    YardComponent,
    YardEntrypoint,
    format_yard_catalog,
    get_component,
    load_components,
)
from ci2lab.harness.yard.runner import execute

__all__ = [
    "YardComponent",
    "YardEntrypoint",
    "execute",
    "format_yard_catalog",
    "get_component",
    "load_components",
]
