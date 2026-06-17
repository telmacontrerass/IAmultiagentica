# Integration contract

This package defines the types shared between:

- **Router** (`ci2lab/hardware`, `ci2lab/router`, `ci2lab/runtime`) — hardware profile and model metadata
- **Harness** (`ci2lab/harness`) — the ReAct agentic loop
- **Pipeline** (`ci2lab/pipeline.py`) — joins user config, router, and harness

## Main types

| Type | Producer | Consumer | Use |
|------|----------|----------|-----|
| `HardwareProfile` | `hardware.scan_hardware()` | `router`, CLI, UI | RAM/VRAM/GPU, inference budget |
| `ModelSpec` | `catalog/models.json` | `router` | Metadata for a catalog model |
| `ModelSelection` | `router.selection.build_model_selection()` | `harness`, `pipeline` | Chosen model + tool_mode + context_length |
| `IntentResult` | `router.classify_intent()` | `router`, CLI | Prompt intent category |

`router.resolve_model()` exists as an optional API (auto-picks the first recommendation); it is **not** used by the production `chat`/`agent`/UI flow.

## Rules

1. Any change to `types.py` must be backward compatible (new fields optional).
2. The router **produces** profiles and metadata; the user **chooses** which model to run.
3. The harness **consumes** `ModelSelection` via `AgentConfig` (built in `pipeline.build_agent_config()`).

## Integration state

- **Suggestions:** `ci2lab models recommend` — the user decides which model to run.
- **Execution:** `pipeline.prepare_session()` + `build_agent_config()` for the CLI, UI, and scripts.

## Full documentation

See [`docs/HARDWARE_ROUTER_HANDOFF.md`](../../docs/HARDWARE_ROUTER_HANDOFF.md).
