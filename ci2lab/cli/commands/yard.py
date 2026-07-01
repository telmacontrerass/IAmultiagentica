"""yard command: browse and run Yard components from the terminal.

Mirrors the ``skills`` command but exposes the Yard's three actions — ``list``
(catalogue), ``describe`` (one component's entrypoints and parameters) and
``run`` (execute an entrypoint) — over the same registry the ``yard`` gateway
tool uses.
"""

from __future__ import annotations

import argparse
import json

from rich.table import Table

from ci2lab.config import Ci2LabConfig
from ci2lab.console import console
from ci2lab.harness.types import AgentConfig
from ci2lab.harness.yard.loader import (
    YardComponent,
    format_yard_catalog,
    get_component,
    load_components,
)
from ci2lab.harness.yard.runner import execute


def _workspace(args: argparse.Namespace, runtime: Ci2LabConfig) -> str:
    """Resolve the effective workspace for Yard discovery."""
    return str(getattr(args, "workspace", None) or runtime.workspace or ".")


def _cmd_yard(args: argparse.Namespace, runtime: Ci2LabConfig) -> int:
    """Dispatch ``ci2lab yard`` to the list/describe/run action.

    Args:
        args: Parsed CLI arguments; ``yard_command`` selects the action.
        runtime: Merged runtime configuration, used for the default workspace.

    Returns:
        Process exit code (``0`` on success, ``1`` on a declined/failed run or a
        bad request).
    """
    cwd = _workspace(args, runtime)
    components = load_components(cwd)
    action = getattr(args, "yard_command", None) or "list"
    if action == "list":
        return _list(args, components)
    if action == "describe":
        return _describe(args, components)
    if action == "run":
        return _run(args, components, cwd)
    console.print(f"Unknown yard action: {action}")
    return 1


def _list(args: argparse.Namespace, components: dict[str, YardComponent]) -> int:
    """List the catalogue as a table (or JSON), optionally filtered by query."""
    query = " ".join(getattr(args, "query", None) or []) or None
    if getattr(args, "json", False):
        catalog = format_yard_catalog(components, query=query, budget_chars=1_000_000)
        listed = {line.split("`")[1] for line in catalog.splitlines() if "`" in line}
        rows = [
            {
                "name": c.name,
                "title": c.title,
                "kind": c.kind,
                "requires": c.requires,
                "tags": c.tags,
                "entrypoints": [ep.function for ep in c.entrypoints],
                "source": c.source,
                "path": str(c.path),
            }
            for c in sorted(components.values(), key=lambda c: c.name)
            if c.name in listed
        ]
        console.print_json(json.dumps(rows, ensure_ascii=False))
        return 0

    catalog = format_yard_catalog(components, query=query)
    if not catalog:
        console.print("No Yard components found.")
        return 0
    listed = {line.split("`")[1] for line in catalog.splitlines() if "`" in line}
    table = Table(title="Yard components")
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("Requires")
    table.add_column("Entrypoints")
    table.add_column("Description")
    for c in sorted(components.values(), key=lambda c: c.name):
        if c.name not in listed:
            continue
        table.add_row(
            c.name,
            c.kind,
            ", ".join(c.requires) or "-",
            str(len(c.entrypoints)),
            c.description,
        )
    console.print(table)
    return 0


def _describe(args: argparse.Namespace, components: dict[str, YardComponent]) -> int:
    """Show one component's entrypoints and parameters."""
    component = get_component(components, args.component)
    if component is None:
        console.print(f"Unknown component: {args.component}")
        return 1
    console.print(f"[bold]{component.name}[/bold] ({component.kind}) — {component.description}")
    if component.requires:
        console.print(f"Requires (pip): {', '.join(component.requires)}")
    table = Table(title="Entrypoints")
    table.add_column("Function")
    table.add_column("Ready")
    table.add_column("Required params")
    table.add_column("Summary")
    for ep in component.entrypoints:
        table.add_row(
            ep.function,
            ep.ready,
            ", ".join(ep.required_params) or "-",
            ep.summary,
        )
    console.print(table)
    return 0


def _run(args: argparse.Namespace, components: dict[str, YardComponent], cwd: str) -> int:
    """Execute one entrypoint and print its JSON result."""
    component = get_component(components, args.component)
    if component is None:
        console.print(f"Unknown component: {args.component}")
        return 1
    entrypoint = component.entrypoint(getattr(args, "entrypoint", None))
    if entrypoint is None:
        names = ", ".join(ep.function for ep in component.entrypoints)
        console.print(f"Pass an entrypoint. Available: {names}")
        return 1
    try:
        call_args = json.loads(getattr(args, "args", None) or "{}")
    except json.JSONDecodeError as exc:
        console.print(f"Invalid --args JSON: {exc}")
        return 1
    if not isinstance(call_args, dict):
        console.print("--args must be a JSON object.")
        return 1
    config = AgentConfig(cwd=cwd, auto_confirm=bool(getattr(args, "yes", False)))
    core_dirs = [c.core_dir for c in components.values()]
    result = execute(component, entrypoint, call_args, core_dirs, config=config)
    console.print_json(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1
