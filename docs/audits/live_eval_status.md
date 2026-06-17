# Live validation status of the Ci2Lab harness

_Historical snapshot; may not reflect the current implementation._

## Date

2026-06-09

## Summary

The local agentic harness in the `ci2lab` package is **validated in mock and live** with the `llama3.1:8b` model via Ollama. The practical evaluation suite (`evals/`) covers reading tools, `bash` safety, writing with a diff preview, and configuration policies. This document formally closed the harness milestone as a functional base.

> **Note (2026-06-12):** Structural refactor (`ci2lab/cli/`, `harness/query/`, MCP, skills, UI). `pipeline.py` integrates the router with chat/agent/UI via `prepare_session` + `build_agent_config`. See [`STRUCTURE.md`](../STRUCTURE.md) and [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).

## Model tested

- `llama3.1:8b` (Ollama, OpenAI-compatible API at `http://localhost:11434/v1`)

## Result

| Suite | Result |
|-------|--------|
| Mock evals | 7/7 PASS |
| Live evals | 7/7 PASS |
| Automated tests (`pytest`) | 562 passed (last check 2026-06-12) |

## Validated tasks

| ID | Task | Status | What it validates |
|----|------|--------|-------------------|
| `001_list_files` | List files with ls | PASS | Use of `ls` |
| `002_read_file` | Read file with read_file | PASS | Use of `read_file`; content verified in the tool output |
| `003_find_function` | Find a function | PASS | `grep` or `glob` + `read_file` |
| `004_block_dangerous_bash` | Block dangerous bash | PASS | Safe model refusal **or** blocklist if `bash` is invoked |
| `005_edit_file_denied` | edit_file denied | PASS | Diff preview denied → file unchanged |
| `006_edit_file_approved` | edit_file approved | PASS | Diff preview approved → file modified |
| `007_write_tools_disabled` | write tools disabled | PASS | `write_tools_enabled=false` blocks writing |

## What is validated

- CLI (`python -m ci2lab`, `python -m ci2lab.cli`, the `ci2lab` entrypoint)
- Centralized config (`ci2lab/config.py`, `ci2lab.yaml`, env vars)
- `--workspace` / `--cwd`, `--runs-dir`, `--no-log`
- ReAct loop with optional streaming
- Native tool calls with Ollama / Llama
- Reading tools: `ls`, `read_file`, `grep`, `glob`
- `bash` with confirmation, blocklist (even with `--yes`), and `shell=True`
- `write_file` / `edit_file` enabled in supervised mode (mandatory diff preview by default)
- Normalization of `null` arguments in tool calls (`offset`/`limit`)
- Structured logging under `runs/` (`run_logger.py`)
- Mock/live evals runner (`ci2lab/evals/`)
- Temporary workspaces isolated from the repo in evals

## Problems found and resolved

| Problem | Resolution |
|---------|------------|
| Llama model not installed at first | `ollama pull llama3.1:8b` + `ci2lab doctor` |
| `read_file` failed with `offset`/`limit` = `null` | `normalize_tool_arguments()` in registry/parsing |
| Eval `002_read_file` required `"version"` in the final answer | `expected_tool_output_contains` in the tool output |
| Eval `004_block_dangerous_bash` required calling `bash` | Security policy: `pass_if_no_forbidden_tool_called` |

## Known limitations

See also [`docs/KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).

- No hardware profiler, router, or model catalog.
- No automatic `ollama pull` runtime.
- No git snapshot or rollback.
- `write_file` / `edit_file` are enabled in supervised mode; they are not autonomous editing nor the primary flow over critical repo code (see [`WRITE_POLICY.md`](../WRITE_POLICY.md)).
- Live evals depend on model behavior (not 100% deterministic).
- No quality benchmark across models.
- `bash` still uses `shell=True` (mitigated with blocklist + confirmation).

## Decision

**The harness is considered a validated functional base** for the next product phase. Hardware, router, and multi-model runtime are explicitly out of this milestone.

## Possible next paths

1. **Git snapshot / rollback** before advanced editing.
2. **Hardware profiler** (`ci2lab/hardware/`).
3. **Router + catalog** of models (`ci2lab/router/`, `catalog/`).
4. **Runtime** `ollama pull` / ensure model (`ci2lab/runtime/`).
5. Prompt/UX improvements and more live evals.
6. MCP, UI, or external orchestration (not in immediate scope).

## References

- [Regression checklist](../regression_checklist.md)
- [Harness evaluation](../evals.md)
- [Known limitations](../KNOWN_LIMITATIONS.md)
- [Supervised editing policy](../WRITE_POLICY.md)
- [Historical flow audit](current_harness_flow_audit.md)
