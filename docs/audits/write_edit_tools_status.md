# Status of `write_file` and `edit_file`

_Historical snapshot; may not reflect the current implementation._

**Date:** 2026-06-09 (updated: supervised editing policy)
**Phase:** editing enabled in supervised mode — **validated** in evals `005`/`006`/`007`, mock and live

## Summary

`write_file` and `edit_file` are **enabled and validated** in **supervised mode**: a mandatory diff preview by default before modifying disk. The user sees a unified diff (or a new-file preview) and must approve. `--yes` **does not skip** the preview when `require_diff_preview=true`.

**Current decision:** editing is available, not autonomous. Every change requires human supervision; it is not the agent's primary flow over critical repository code. Full policy: [`docs/WRITE_POLICY.md`](../WRITE_POLICY.md). Disable entirely with `write_tools_enabled: false`.

## Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `write_tools_enabled` | `true` | If `false`, write/edit return an error without running |
| `require_diff_preview` | `true` | If `true`, always shows the diff and asks for confirmation |

Sources: `ci2lab.yaml`, `CI2LAB_WRITE_TOOLS_ENABLED`, `CI2LAB_REQUIRE_DIFF_PREVIEW`, `AgentConfig`.

When `require_diff_preview=false`, write/edit follow the standard confirmation flow (`--yes` can auto-approve).

## Flow

1. The model invokes `write_file` or `edit_file`.
2. If `write_tools_enabled=false` → `outcome: blocked_by_config`.
3. A preview is generated (`harness/tools/write_preview.py`):
   - **edit_file:** unified diff before/after the replacement.
   - **write_file (existing):** diff of current content vs new.
   - **write_file (new):** a creation message + a preview of the content.
4. If validation fails (e.g. `old_string` not found) → `outcome: failed` without touching disk.
5. If `require_diff_preview=true` → a Rich panel with the diff → `[y/N]` confirmation.
6. If denied → `outcome: denied`, file unchanged.
7. If approved → it runs and `outcome: approved`.

`bash` does not use a diff preview; `--yes` still auto-confirms bash (except for the blocklist).

## Logging (`tool_calls.jsonl`)

Each write/edit invocation records an `outcome`:

- `approved`
- `denied`
- `blocked_by_config`
- `failed`

## Code inventory

| Location | `write_file` | `edit_file` |
|----------|--------------|-------------|
| `TOOL_NAMES` / dispatch | Yes | Yes |
| `write_preview.py` | Yes | Yes |
| `write_permissions.py` | Yes | Yes |
| confirm tools (no-preview mode) | Yes | Yes |

## Out of scope

- Git rollback / auto-commit
- Diff preview for `bash`
- Graphical UI
