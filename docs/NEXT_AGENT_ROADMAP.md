# Next Agent Roadmap

This document captures the next heavier changes after the UI agents-mode cleanup,
skills listing, and the initial hook lifecycle.

## 4. `run_tests` Tool

Goal: give models a safe, structured way to run the project test suite without
guessing commands through `bash`.

Plan:

1. Add a `run_tests` tool schema with arguments for `scope`, `target`, `extra_args`,
   and `timeout_seconds`.
2. Detect the project test runner from repository files in priority order:
   `pyproject.toml`, `package.json`, `pytest.ini`, `tox.ini`, `Cargo.toml`.
3. Keep execution workspace-bound and reuse the existing security profile checks.
4. Return structured output: command, exit code, duration, truncated stdout/stderr,
   and a short failure summary.
5. Add tests for Python, Node, unknown project, timeout, and blocked command cases.

Suggested files:

- `ci2lab/harness/tools/schemas_parts/registry.py`
- `ci2lab/harness/tools/executor.py` or a new `executor_parts/tests.py`
- `tests/test_run_tests_tool.py`

## 5. Repo Map / Codebase Index

Goal: let the model understand repository shape quickly before reading files.

Plan:

1. Add a repo-map builder that scans files with ignore rules from `.gitignore`,
   size limits, and language-aware summaries.
2. Store an ephemeral JSON index under the run log directory, not in the repo by
   default.
3. Expose a `repo_map` tool returning modules, symbols where cheap to extract,
   dependency files, test directories, docs, and likely entry points.
4. Inject a compact repo-map summary into the first agent round for coding tasks.
5. Add snapshot tests with small synthetic repos.

Suggested files:

- `ci2lab/harness/context/repo_map.py`
- `ci2lab/harness/tools/schemas_parts/registry.py`
- `tests/test_repo_map.py`

## 6. Vector / Project Memory

Goal: make reusable project knowledge searchable across sessions without relying
only on raw chat history.

Plan:

1. Start with a pluggable local store interface and a simple file-backed SQLite
   implementation.
2. Index project docs, `CI2LAB.md`, `AGENTS.md`, skill metadata, and selected
   final summaries from successful runs.
3. Add a `memory_search` tool with source paths, timestamps, and relevance scores.
4. Add explicit opt-in settings before indexing large repos or user home content.
5. Keep deletion and rebuild commands simple: `ci2lab memory rebuild`, `search`,
   and `clear`.

Suggested files:

- `ci2lab/harness/memory/`
- `ci2lab/cli/commands/memory.py`
- `tests/test_memory.py`

## 7. Local Benchmark Feedback Loop

Goal: replace static model quality assumptions with project-local measurements.

Plan:

1. Extend eval tasks to record model, hardware, latency, token usage, success,
   tool failures, and final score.
2. Persist benchmark history locally under `~/.ci2lab/benchmarks/`.
3. Feed aggregate results back into `models recommend` and UI model cards.
4. Add a small default suite covering coding, reading, tool use, and Spanish/English
   instruction following.
5. Add a regression command for comparing two local models on the same tasks.

Suggested files:

- `ci2lab/evals/`
- `ci2lab/router/recommend.py`
- `ci2lab/ui/server_parts/api.py`
- `tests/test_benchmark_feedback.py`
