"""Discover Yard components from ``COMPONENT.md`` manifests.

A Yard component is a directory containing a ``COMPONENT.md`` manifest and a
``core/`` folder of vendored Python modules. The manifest mirrors the
``SKILL.md`` convention used elsewhere in the harness: a ``---`` delimited
frontmatter block of scalar metadata, followed by a body. The body carries one
fenced ```json`` manifest block describing the runnable entrypoints (kept
machine-readable) and free-form prose after it (the human/model-readable
porting guide).

Components are merged from three roots in increasing precedence — the built-in
set shipped with the package, a user root under ``~/.ci2lab/yard`` and a
workspace root under ``<cwd>/.ci2lab/yard`` — so a workspace may override or add
components without touching the package.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_COMPONENT_BODY_CHARS = 16_000
MAX_CATALOG_CHARS = 8_000
COMPONENT_FILENAME = "COMPONENT.md"

#: Execution readiness of an entrypoint, gating what :mod:`runner` will do.
#:
#: - ``pure``: self-contained, runs with no secrets or side effects.
#: - ``needs_key``: performs network calls; one or more parameters are API keys
#:   that must be supplied by the caller before it will execute.
#: - ``needs_config``: the salvaged source has redacted prompts/schemas and
#:   cannot run correctly; the runner refuses and points at the porting guide.
#: - ``side_effect``: mutates the host (opens windows, spawns processes); the
#:   runner requires an explicit ``confirm`` flag.
READINESS = frozenset({"pure", "needs_key", "needs_config", "side_effect"})


@dataclass
class YardEntrypoint:
    """A single callable exposed by a component.

    Attributes:
        function: Name of the function to call inside ``module``.
        module: Importable module name under the component's ``core/`` folder.
        summary: One-line description of what the entrypoint does.
        ready: One of :data:`READINESS`; controls the runner's gating.
        parameters: JSON-Schema-style object describing the call arguments.
        secret_params: Parameter names that hold credentials (used by the
            ``needs_key`` gate to check they were supplied).
        requires: Third-party pip packages needed to *import* this entrypoint's
            module (checked before execution). Declared per-entrypoint because a
            module's pure helpers may need nothing while an LLM entrypoint in the
            same module needs a heavy SDK.
        note: Optional extra guidance surfaced by ``describe`` and by the runner
            when it declines to execute.
    """

    function: str
    module: str
    summary: str
    ready: str
    parameters: dict[str, Any] = field(default_factory=dict)
    secret_params: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    note: str | None = None

    @property
    def required_params(self) -> list[str]:
        """Return the required parameter names declared in the schema."""
        req = self.parameters.get("required", [])
        return [str(p) for p in req] if isinstance(req, list) else []


@dataclass
class YardComponent:
    """A salvaged, runnable component discovered from a ``COMPONENT.md`` file.

    Attributes:
        name: Unique slug used to address the component from the tool.
        title: Human-readable name.
        description: Short description shown in the catalogue.
        when_to_use: Optional guidance on when the component applies.
        kind: Component category (e.g. ``utility``, ``api-client``).
        tags: Searchable tags used by the catalogue query filter.
        requires: Third-party pip dependencies the ``core/`` modules import.
        source_repo: Repository the component was salvaged from (provenance).
        yard_id: Original Quarry-Yard id (provenance).
        signature: Original sha256 signature of the salvaged source (provenance).
        core_dir: Path to the component's ``core/`` module folder.
        entrypoints: The callables the component exposes.
        body: The porting-guide prose (manifest block stripped), possibly
            truncated.
        source: Origin root: ``builtin``, ``user`` or ``workspace``.
        path: Filesystem path to the ``COMPONENT.md`` file.
    """

    name: str
    title: str
    description: str
    when_to_use: str | None
    kind: str
    tags: list[str]
    requires: list[str]
    source_repo: str | None
    yard_id: str | None
    signature: str | None
    core_dir: Path
    entrypoints: list[YardEntrypoint]
    body: str
    source: str
    path: Path

    def entrypoint(self, name: str | None) -> YardEntrypoint | None:
        """Resolve an entrypoint by function name.

        Args:
            name: The entrypoint's ``function`` name. When ``None`` and the
                component exposes exactly one entrypoint, that entrypoint is
                returned.

        Returns:
            The matching :class:`YardEntrypoint`, or ``None`` if not found.
        """
        if name is None:
            return self.entrypoints[0] if len(self.entrypoints) == 1 else None
        for ep in self.entrypoints:
            if ep.function == name:
                return ep
        return None


def _user_yard_root() -> Path:
    """Return the root directory for user-level Yard components."""
    return Path.home() / ".ci2lab" / "yard"


def _workspace_yard_root(cwd: str) -> Path:
    """Return the root directory for workspace Yard components under ``cwd``."""
    return Path(cwd).resolve() / ".ci2lab" / "yard"


def _builtin_yard_root() -> Path:
    """Return the root directory for Yard components shipped with the package."""
    return Path(__file__).resolve().parent / "builtin"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse ``---`` delimited scalar frontmatter, returning (meta, body).

    Args:
        text: Raw file contents, optionally beginning with a frontmatter block.

    Returns:
        A ``(meta, body)`` tuple. ``meta`` maps normalised keys (lower-cased,
        hyphens to underscores) to their string values; ``body`` is the
        remaining text. ``meta`` is empty when no frontmatter is present.
    """
    if not text.startswith("---"):
        return {}, text.strip()
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    body = text[match.end() :].strip()
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace("-", "_")
        value = value.strip().strip("'\"")
        if value:
            meta[key] = value
    return meta, body


def _split_list(raw: str | None) -> list[str]:
    """Split a comma/whitespace-separated frontmatter value into items."""
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[,\s]+", raw) if part.strip()]


def _extract_manifest(body: str) -> tuple[dict[str, Any], str]:
    """Pull the first fenced ```json`` block out of ``body``.

    Args:
        body: The manifest body following the frontmatter.

    Returns:
        A ``(manifest, prose)`` tuple: the parsed JSON object (empty on absence
        or parse error) and the body with the JSON block removed.
    """
    match = re.search(r"```json\s*\n(.*?)\n```", body, re.DOTALL)
    if not match:
        return {}, body
    try:
        manifest = json.loads(match.group(1))
    except json.JSONDecodeError:
        manifest = {}
    prose = (body[: match.start()] + body[match.end() :]).strip()
    if not isinstance(manifest, dict):
        return {}, prose
    return manifest, prose


def _parse_entrypoints(manifest: dict[str, Any]) -> list[YardEntrypoint]:
    """Build :class:`YardEntrypoint` objects from a manifest's ``entrypoints``."""
    entrypoints: list[YardEntrypoint] = []
    for raw in manifest.get("entrypoints", []) or []:
        if not isinstance(raw, dict):
            continue
        function = str(raw.get("function", "")).strip()
        module = str(raw.get("module", "")).strip()
        if not function or not module:
            continue
        ready = str(raw.get("ready", "pure")).strip()
        if ready not in READINESS:
            ready = "needs_config"
        params = raw.get("parameters")
        secret = raw.get("secret_params", [])
        requires = raw.get("requires", [])
        entrypoints.append(
            YardEntrypoint(
                function=function,
                module=module,
                summary=str(raw.get("summary", "")).strip(),
                ready=ready,
                parameters=params if isinstance(params, dict) else {},
                secret_params=[str(s) for s in secret] if isinstance(secret, list) else [],
                requires=[str(r) for r in requires] if isinstance(requires, list) else [],
                note=str(raw["note"]).strip() if raw.get("note") else None,
            )
        )
    return entrypoints


def _load_component_file(path: Path, source: str) -> YardComponent | None:
    """Read and parse a single ``COMPONENT.md`` into a :class:`YardComponent`.

    Returns ``None`` when the file cannot be read or declares no entrypoints
    (a manifest with no runnable entrypoint is not a usable component).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = parse_frontmatter(text)
    manifest, prose = _extract_manifest(body)
    entrypoints = _parse_entrypoints(manifest)
    if not entrypoints:
        return None
    core_dir = path.parent / "core"
    if not core_dir.is_dir():
        return None
    name = meta.get("name") or path.parent.name
    if len(prose) > MAX_COMPONENT_BODY_CHARS:
        prose = prose[:MAX_COMPONENT_BODY_CHARS] + "\n... (porting guide truncated)"
    return YardComponent(
        name=name,
        title=meta.get("title") or name,
        description=meta.get("description") or f"Yard component {name}",
        when_to_use=meta.get("when_to_use"),
        kind=meta.get("kind") or "component",
        tags=_split_list(meta.get("tags")),
        requires=_split_list(meta.get("requires")),
        source_repo=meta.get("source_repo"),
        yard_id=meta.get("yard_id"),
        signature=meta.get("signature"),
        core_dir=core_dir,
        entrypoints=entrypoints,
        body=prose,
        source=source,
        path=path,
    )


def _scan_yard_dir(root: Path, source: str) -> dict[str, YardComponent]:
    """Discover components under ``root``, keyed by component name."""
    components: dict[str, YardComponent] = {}
    if not root.is_dir():
        return components
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / COMPONENT_FILENAME
        if not manifest_path.is_file():
            continue
        component = _load_component_file(manifest_path, source)
        if component:
            components[component.name] = component
    return components


def load_components(cwd: str) -> dict[str, YardComponent]:
    """Load Yard components; user overrides built-in, workspace overrides both.

    Args:
        cwd: Current working directory used to locate workspace components.

    Returns:
        A mapping of component name to :class:`YardComponent`, merged across the
        built-in, user and workspace roots in increasing precedence.
    """
    merged: dict[str, YardComponent] = {}
    merged.update(_scan_yard_dir(_builtin_yard_root(), "builtin"))
    merged.update(_scan_yard_dir(_user_yard_root(), "user"))
    merged.update(_scan_yard_dir(_workspace_yard_root(cwd), "workspace"))
    return merged


def _matches_query(component: YardComponent, query: str) -> bool:
    """Return whether ``component`` matches a lower-cased free-text ``query``."""
    haystack = " ".join(
        [
            component.name,
            component.title,
            component.description,
            component.kind,
            " ".join(component.tags),
        ]
    ).lower()
    return all(term in haystack for term in query.lower().split())


def format_yard_catalog(
    components: dict[str, YardComponent],
    *,
    query: str | None = None,
    budget_chars: int = MAX_CATALOG_CHARS,
) -> str:
    """Render the component catalogue as a bullet list, bounded by a budget.

    Args:
        components: Components to include, keyed by name.
        query: Optional free-text filter; only components whose name, title,
            description, kind or tags contain every whitespace-separated term
            are listed.
        budget_chars: Maximum length of the rendered catalogue before it is
            truncated.

    Returns:
        A newline-separated bullet list of components, truncated to
        ``budget_chars``; an empty string when nothing matches.
    """
    selected = [
        c
        for c in sorted(components.values(), key=lambda c: c.name)
        if not query or _matches_query(c, query)
    ]
    if not selected:
        return ""
    lines: list[str] = []
    for c in selected:
        desc = c.description
        if len(desc) > 180:
            desc = desc[:179] + "…"
        tags = f" [{', '.join(c.tags[:6])}]" if c.tags else ""
        lines.append(f"- `{c.name}` ({c.kind}): {desc}{tags}")
    text = "\n".join(lines)
    if len(text) > budget_chars:
        text = text[: budget_chars - 20] + "\n... (catalog truncated)"
    return text


def get_component(components: dict[str, YardComponent], name: str) -> YardComponent | None:
    """Look up a component by name.

    Args:
        components: Components to search, keyed by name.
        name: The component name to retrieve.

    Returns:
        The matching :class:`YardComponent`, or ``None`` when absent.
    """
    return components.get(name)
