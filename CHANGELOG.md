# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **The Yard** (`ci2lab/harness/yard/`, `docs/YARD.md`): a catalogue of reusable,
  runnable components salvaged from other projects, exposed behind a single
  `yard` gateway tool with progressive disclosure (`list` / `describe` / `run`),
  so the per-turn tool schema stays constant no matter how many components exist.
  Components are data-driven `COMPONENT.md` manifests (mirroring `SKILL.md`) plus
  vendored `core/` code; discovery is char-budgeted and query-filterable and
  merges built-in, user and workspace roots. Execution runs **out-of-process**
  (a short-lived worker with a kill-timeout) and is gated by readiness
  (`pure` / `needs_key` / `needs_config` / `side_effect`), the security profile,
  workspace path-confinement, write-tool confirmation, and a load-time
  `core_sha256` integrity check. Browse and run from the CLI (`ci2lab yard …`) or
  the REPL (`/yard`); ships six components salvaged from *Proyecto-Alvaro*.
- **MIT License** (`LICENSE`), wired into the project metadata.
- **Pluggable LLM backends** (`ci2lab/harness/backends/`): an `LLMBackend`
  interface with `OllamaBackend` (native `/api/chat`) and `OpenAICompatBackend`
  (`/v1`, for vLLM / LM Studio / llama.cpp), selected by `create_backend()`.
- **Single-file provider seam:** `backend` setting in `ci2lab.yaml` /
  `CI2LAB_BACKEND` flows through the pipeline to the transport, so swapping the
  model or inference server is a configuration-only change.
- Hardware-aware context-window sizing: models default to their native maximum
  window, capped to what the scanned VRAM/RAM can hold.
- Tooling: `ruff` and `mypy` configuration; GitHub Actions CI running lint,
  format-check, strict type-checking of the core packages, and the test suite.
- `py.typed` marker so downstream consumers get the package's type information.
- `tests/test_tool_registry_consistency.py` cross-checks the tool registries.

### Fixed
- `analyze_image` was advertised to the model and implemented but missing from
  `TOOL_NAMES`, so calls were rejected as unknown; it is now registered.
- Duplicate `"search"` key in the tool-name alias map (the earlier mapping was
  silently shadowed).
- Identical-branch conditional in the fenced tool-call parser.

### Changed
- `LLMClient` is now a thin facade over the backend layer (API unchanged).
- Google-style docstrings and complete type hints across the core, security,
  multi-agent, context, evals and UI packages.
- Whole codebase formatted with `ruff format`.
