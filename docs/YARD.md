# The Yard

The **Yard** is a data-driven catalogue of reusable, *runnable* code components
salvaged from other projects. Unlike a **skill** (a markdown *playbook* the model
reads), a Yard component ships executable Python: a single gateway tool lists the
catalogue, describes one component's entrypoints on demand, and executes an
entrypoint server-side — returning only the result, never the source.

The design goal is **progressive disclosure**: the per-turn tool schema stays
constant no matter how many components exist. The model sees exactly one tool
(`yard`); the catalogue, a component's parameter schema, and the source code
enter context only when pulled — the same trick the harness uses for skills.

## Where things live

```
ci2lab/harness/yard/
  loader.py            # COMPONENT.md → YardComponent/YardEntrypoint registry
  runner.py            # execute one entrypoint (readiness + permission + deps gates)
  builtin/<slug>/
    COMPONENT.md       # manifest: frontmatter + a fenced-json entrypoint block + prose
    core/*.py          # the vendored, runnable modules
ci2lab/harness/tools/yard_tool.py   # the single `yard` gateway tool (list/describe/run)
```

Components are merged from three roots in increasing precedence, mirroring
skills: the built-in set shipped with the package, a user root under
`~/.ci2lab/yard`, and a workspace root under `<cwd>/.ci2lab/yard`. **Adding a
component is just dropping a directory in** — there is no per-component code to
edit and nothing to register (the `yard` tool's schema never changes).

## The `COMPONENT.md` manifest

Mirrors the `SKILL.md` convention: `---` delimited scalar frontmatter, then a
body. The body carries **one fenced ` ```json ` block** describing the runnable
entrypoints (machine-readable) followed by free-form prose (the porting guide).

```markdown
---
name: geo_toolkit
title: Geospatial toolkit — haversine, grid, distance matrix
description: Great-circle distance, grid tiling, and a Distance Matrix client.
when_to_use: Distance between lat/lon points, tiling a rectangle, walking distances.
kind: utility
tags: geospatial, haversine, grid-search
requires: requests
yard_id: yard-173c5687f9
source_repo: Proyecto-Alvaro
signature: sha256:...
---

​```json
{
  "entrypoints": [
    {
      "function": "calcular_distancia_haversine",
      "module": "geometria",
      "ready": "pure",
      "summary": "Great-circle distance in metres between two lat/lon points.",
      "parameters": {"type": "object", "properties": {"lat1": {"type": "number"}, ...},
                     "required": ["lat1", "lon1", "lat2", "lon2"]}
    }
  ]
}
​```

# Porting guide prose ...
```

Per-entrypoint fields: `function`, `module` (a file under `core/`), `ready`,
`summary`, `parameters` (JSON-Schema-style), optional `secret_params`,
`requires` (pip deps needed to *import* this entrypoint's module), and `note`.

## The gateway tool

One tool, three actions — its schema is tiny and constant:

| Action | What enters context | When |
|--------|---------------------|------|
| `yard(action="list", query?)` | catalogue summaries, char-budgeted, tag/name-filterable | on demand |
| `yard(action="describe", component)` | one component's entrypoints + param schemas | on demand |
| `yard(action="run", component, entrypoint?, args?)` | the return value only — never the source | on execution |

Large results ride the executor's central output-offload path (preview in
context, full result saved under `.ci2lab/tool_outputs/`).

## Readiness gating

Salvaged code is unvetted and some entrypoints were sanitised or touch the host,
so the runner classifies each entrypoint by `ready` and gates accordingly:

| `ready` | Runner behaviour |
|---------|------------------|
| `pure` | self-contained; runs freely |
| `needs_key` | performs network calls; a listed `secret_params` (e.g. `api_key`) must be supplied, else declined |
| `needs_config` | salvaged source has redacted prompts/schemas; **never executes** — returns the porting guide |
| `side_effect` | mutates the host; refused when write tools are disabled, otherwise routed through the harness confirmation channel (`auto_confirm` / `confirm_callback`) |

Before executing, the runner also checks that each entrypoint's `requires`
dependencies are importable. All gates return a structured result dictionary
(`ok`, `status`, `message`) — execution never raises.

## Security

Execution is **in-process** but governed: the `yard` tool call goes through the
normal permission layer (classified `allow`, like `skill`/`mcp_call`), and
host-mutating (`side_effect`) entrypoints additionally route through the same
confirmation channel the write tools use. Untrusted third-party sources live only
under `core/` and are excluded from lint/type-checking; they are loaded lazily by
the runner, never imported at package import time. For stronger isolation, the
same registry can be fronted by an external MCP server (out-of-process).

## Using it

From the model: call the `yard` tool. From the terminal:

```bash
ci2lab yard list [query...]                 # browse the catalogue
ci2lab yard describe <component>            # entrypoints + parameters
ci2lab yard run <component> [entrypoint] --args '{"...": ...}' [--yes]
```

From the REPL: `/yard` lists the catalogue; `/yard <component>` shows its
entrypoints. (Execution from the REPL is via the agent, which calls the tool.)

## The built-in components

Six components salvaged from *Proyecto-Alvaro*: `boolean_coercion` (tri-state
cell → bool), `geo_toolkit` (haversine / grid / Distance Matrix), `window_layout`
(multi-monitor two-window browser layout), `llm_enricher` (structured-output LLM
enrichment with cache + anti-hallucination), `places_client` (Google Places grid
search), and `facade_estimator` (Street View + vision-LLM classification). Their
pure entrypoints run as-is; the network/LLM ones are gated per the table above.
