# Structured run logging (runs/)

_Historical snapshot; may not reflect the current implementation._

**Date:** 2026-06-09
**Module:** `ci2lab/harness/run_logger.py`

## Goal

Persist every agent run into a folder under `runs/` without changing the functional behavior of the ReAct loop. Write failures emit a warning and do not interrupt the run.

## Activation

| Mechanism | Default |
|-----------|---------|
| Default behavior | Logging **enabled** |
| `--no-log` (CLI) | Disables |
| `CI2LAB_NO_LOG=1` | Disables |
| `no_log: true` in `ci2lab.yaml` | Disables |
| `log_runs: false` in `ci2lab.yaml` | Disables |

Base directory:

- Default: `runs/`
- `--runs-dir <path>`, or `CI2LAB_RUNS_DIR`, or `runs_dir` in yaml

## Folder structure

```text
runs/
  2026-06-09_143022_a1b2c3d4/
    run_summary.json
    conversation.json
    tool_calls.jsonl
    final_answer.md
    config_snapshot.json
```

Name: `YYYY-MM-DD_HHMMSS_<short_id>` (local time + 8 hex).

## Artifacts

### `run_summary.json`

Run metadata: timestamps, duration, model, `backend_url`, `tool_mode`, `workspace`, `max_rounds`, `stream`, `auto_confirm`, rounds, tool count, `tools_used`, `status`, `error` if applicable.

**Status:** `success` | `llm_error` | `max_rounds` | `interrupted`

### `conversation.json`

```json
{ "messages": [ /* internal history compatible with the loop */ ] }
```

Includes `system`, `user`, `assistant` (with `tool_calls` if applicable), and `tool`.

### `tool_calls.jsonl`

One JSON line per invocation:

- `round`, `tool_call_id`, `tool`, `arguments`
- `started_at`, `ended_at`, `duration_ms`
- `ok` (inverse of `is_error`)
- `output` (truncated to 2000 characters in the log)
- `error` if the tool failed
- `outcome` (`approved`, `denied`, `blocked_by_config`, `failed`; relevant for `write_file` / `edit_file`)

### `final_answer.md`

The final text returned by `run_agent`.

### `config_snapshot.json`

Effective config without secrets: `resolved` (CLI/env/yaml) and `selection` (`ModelSelection`) blocks.

## Integration

```text
cli._build_config() → AgentConfig(run_log_enabled, runs_dir, config_snapshot)
  ↓
loop.run_agent() → RunLogger.maybe_create() → start()
  ↓
per tool → record_tool_call() → append tool_calls.jsonl
  ↓
finally → finalize() → remaining artifacts
```

## Security and privacy

- Full environment variables are not dumped.
- `config_snapshot` includes only known configuration fields.
- Tool output in the log is truncated.

## Automated tests

See `tests/test_run_logger.py`.
