# Contributing to ci2lab

Thanks for working on ci2lab. This guide covers the local workflow and the
quality bar that CI enforces.

## Development setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1     # Windows
# source .venv/bin/activate      # macOS/Linux
pip install -e ".[dev]"
```

## Quality gates

Every change must pass the same checks CI runs (`.github/workflows/ci.yml`):

```bash
python -m ruff check ci2lab tests      # lint
python -m ruff format ci2lab tests     # auto-format (run before committing)
python -m mypy ci2lab                    # type-check (baseline repo-wide, strict on core)
python -m pytest -q                     # full test suite
```

Configuration for all of these lives in `pyproject.toml`.

## Code standards

- **Type hints** on every function signature (params and return). New or edited
  modules should pass `mypy --strict`; the strict-checked package list in
  `[[tool.mypy.overrides]]` is expected to grow until it covers everything.
- **Google-style docstrings** on every public module, class and function
  (`Args:`, `Returns:`, `Raises:` where relevant). `ci2lab/harness/backends/`
  and `ci2lab/pipeline.py` are the reference for the expected style.
- **Modularity:** keep modules focused. Façade modules that re-export internals
  are exempt from the unused-import rule via `[tool.ruff.lint.per-file-ignores]`
  — add new façades there rather than scattering `# noqa`.
- **No behavior change without a test.** The suite is the safety net for
  refactors; keep it green at every step.

## Adding a tool

A built-in tool is declared in four places that must stay in sync —
`TOOL_NAMES` (registry), `DISPATCH` (dispatch), its JSON schema (`schemas_parts`)
and its capability category (`capabilities`). `tests/test_tool_registry_consistency.py`
fails fast if they drift.

## Adding an inference backend

Implement an `LLMBackend` subclass in `ci2lab/harness/backends/` and register it
in `factory.py`. No other code should need to change; selecting it is a config
setting (`backend` in `ci2lab.yaml`).
