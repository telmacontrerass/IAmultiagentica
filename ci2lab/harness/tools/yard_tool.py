"""The single ``yard`` gateway tool: list, describe and run Yard components.

Progressive disclosure keeps the per-turn tool schema constant no matter how
many components exist. The model sees exactly one tool; it pulls the catalogue
with ``list``, a single component's entrypoint schema with ``describe``, and
executes an entrypoint with ``run`` (which returns only the result, never the
source). All three actions are backed by the data-driven registry in
:mod:`ci2lab.harness.yard.loader`, so adding a component is a matter of dropping
a directory under a Yard root — no change here.
"""

from __future__ import annotations

import json
from typing import Any

from ci2lab.harness.types import AgentConfig
from ci2lab.harness.yard import loader, runner
from ci2lab.harness.yard.loader import YardComponent


def _render_catalog(components: dict[str, YardComponent], query: str | None) -> str:
    """Render the ``list`` action's catalogue with a short header."""
    catalog = loader.format_yard_catalog(components, query=query)
    if not catalog:
        scope = f" matching `{query}`" if query else ""
        return f"No Yard components found{scope}."
    header = (
        "# Yard catalog\n\n"
        "Reusable, runnable components. Use `yard` with `action=describe` and a "
        "`component` to see its entrypoints and parameters, then `action=run` to "
        "execute one.\n"
    )
    if query:
        header += f"\nFilter: `{query}`\n"
    return f"{header}\n{catalog}"


def _render_describe(component: YardComponent) -> str:
    """Render the ``describe`` action for one component."""
    lines = [
        f"# Yard component: {component.name}",
        "",
        f"**{component.title}** ({component.kind})",
        "",
        component.description,
    ]
    if not component.verified:
        lines += [
            "",
            "> ⚠️ **Unverified:** the vendored code does not match its recorded "
            "`core_sha256` signature. Execution is refused until the signature is "
            "regenerated.",
        ]
    if component.when_to_use:
        lines += ["", f"**When to use:** {component.when_to_use}"]
    if component.requires:
        lines += ["", f"**Requires (pip):** {', '.join(component.requires)}"]
    prov = ", ".join(
        p
        for p in (
            f"repo {component.source_repo}" if component.source_repo else "",
            component.yard_id or "",
        )
        if p
    )
    if prov:
        lines += ["", f"**Provenance:** {prov}"]
    lines += ["", "## Entrypoints", ""]
    for ep in component.entrypoints:
        lines.append(f"### `{ep.function}`  —  _{ep.ready}_")
        if ep.summary:
            lines.append(ep.summary)
        if ep.note:
            lines.append(f"> {ep.note}")
        lines.append("")
        lines.append("Parameters:")
        lines.append("```json")
        lines.append(json.dumps(ep.parameters, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    if component.body:
        lines += ["## Porting guide", "", component.body]
    return "\n".join(lines).rstrip() + "\n"


def _render_run(
    config: AgentConfig,
    components: dict[str, YardComponent],
    component_name: str | None,
    entrypoint_name: str | None,
    args: dict[str, Any] | None,
) -> str:
    """Execute one entrypoint and render the result dictionary as JSON."""
    if not component_name:
        return "Error: `run` requires a `component` name."
    component = loader.get_component(components, component_name)
    if component is None:
        available = ", ".join(sorted(components)) or "(none)"
        return f"Error: unknown component `{component_name}`. Available: {available}"
    entrypoint = component.entrypoint(entrypoint_name)
    if entrypoint is None:
        names = ", ".join(ep.function for ep in component.entrypoints)
        if entrypoint_name:
            return (
                f"Error: component `{component_name}` has no entrypoint "
                f"`{entrypoint_name}`. Available: {names}"
            )
        return (
            f"Error: component `{component_name}` exposes several entrypoints; "
            f"pass one as `entrypoint`. Available: {names}"
        )
    core_dirs = [c.core_dir for c in components.values()]
    result = runner.execute(component, entrypoint, args or {}, core_dirs, config=config)
    return json.dumps(result, ensure_ascii=False, indent=2)


def run_yard(
    config: AgentConfig,
    action: str,
    component: str | None = None,
    entrypoint: str | None = None,
    args: dict[str, Any] | None = None,
    query: str | None = None,
) -> str:
    """Dispatch a ``yard`` tool call to the list/describe/run action.

    Args:
        config: Active agent configuration; ``config.cwd`` locates workspace and
            user Yard roots in addition to the built-in set.
        action: One of ``list``, ``describe`` or ``run``.
        component: Component name (required for ``describe`` and ``run``).
        entrypoint: Entrypoint function name (for ``run``; optional when the
            component exposes exactly one entrypoint).
        args: Argument object forwarded to the entrypoint on ``run``.
        query: Optional free-text filter for ``list``.

    Returns:
        The rendered catalogue, component description, or JSON run result; or a
        human-readable ``Error:`` string for an unknown action or bad request.
    """
    components = loader.load_components(config.cwd)
    action = (action or "").strip().lower()
    if action == "list":
        return _render_catalog(components, query)
    if action == "describe":
        if not component:
            return "Error: `describe` requires a `component` name."
        found = loader.get_component(components, component)
        if found is None:
            available = ", ".join(sorted(components)) or "(none)"
            return f"Error: unknown component `{component}`. Available: {available}"
        return _render_describe(found)
    if action == "run":
        return _render_run(config, components, component, entrypoint, args)
    return f"Error: unknown action `{action}`. Use one of: list, describe, run."
