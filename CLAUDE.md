# CLAUDE.md

Guidance for AI coding agents (Claude Code and similar) working in this
repository. Humans should read [`README.md`](README.md) and
[`CONTRIBUTING.md`](CONTRIBUTING.md) first.

## What this is

`ci2lab` is a local-first agentic CLI: it profiles the host hardware,
recommends/serves an open-source model, and runs a tool-using ReAct agent in the
terminal and a local web UI. All product code lives in the `ci2lab/` package.

## Quality gates (run before finishing any change)

```bash
python -m ruff check ci2lab tests      # lint — must be clean
python -m ruff format ci2lab tests     # format — run before committing
python -m mypy ci2lab                  # type-check — must be clean (strict on core)
python -m pytest -q                    # ~905 tests — must stay green
```

CI (`.github/workflows/ci.yml`) runs all four on Python 3.11 and 3.12. Keep the
working tree green at every step; the test suite is the safety net for refactors.

## Architecture (where things live)

Request flow: `cli`/`ui` → `config` → `pipeline.prepare_session` → `router` →
`pipeline.build_agent_config` → `harness.query.run_agent` →
`harness.backends` (transport) + `harness.tools` (parse → dispatch → execute).

- `contracts/types.py` — shared dataclasses (`ModelSpec`, `ModelSelection`, …).
- `router/` + `catalog/models.json` — model selection and the catalog.
- `harness/backends/` — pluggable LLM transports behind `LLMBackend`.
- `harness/query/loop.py` — the ReAct loop (`run_agent`).
- `harness/tools/` — tool registry, parsing, dispatch, execution.
- `harness/multiagent/` — role orchestration + grounded peer-review flow.
- `security/` — permission engines and audits.

Full map: [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

## Conventions and invariants

- **Docstrings:** Google-style on every public module/class/function. The
  `harness/backends/` package and `pipeline.py` are the reference standard.
- **Types:** annotate every signature. `mypy ci2lab` must pass; the packages in
  `[[tool.mypy.overrides]]` are held to the strict bar (`disallow_untyped_defs`)
  — grow that list, don't shrink it.
- **Tool registries must agree.** A tool is declared in `TOOL_NAMES`, `DISPATCH`,
  its JSON schema, and a capability set. `tests/test_tool_registry_consistency.py`
  fails on drift — update all of them together.
- **Façade modules** re-export internals (often `import x as _x`); they are
  exempt from unused-import (F401) via `[tool.ruff.lint.per-file-ignores]`. Never
  let `ruff --fix` strip those imports; add new façades to that list.
- **The ReAct loop is task-agnostic.** Robustness comes from generic mechanisms
  (loop detection, error-streak cutoff, nudges). Do not add per-topic special
  cases, and be cautious editing the round loop — its nudge/round timing is
  fragile and easy to break.

## Don't commit

Data files (PDFs, images, scratch) belong outside the repo root — they are
git-ignored. Keep prose under `docs/` and bundled assets inside the package.
