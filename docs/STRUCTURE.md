# IAmultiagentica project structure

All of the **product code** lives in the `ci2lab/` package. The surrounding
`Ci2Lab/` workspace only holds reference repos (claude-code, odysseus, opencode,
deepagents) that are **not** part of this package.

## Data flow (one request, end to end)

```text
User
  → ci2lab chat | agent | ui                      cli/ , ui/
  → cli/runtime: merge_cli_config → Ci2LabConfig   config.py
  → pipeline.prepare_session()  → ModelSelection   pipeline.py + router/
  → pipeline.build_agent_config() → AgentConfig
  → harness.query.run_agent()  (or harness.repl.run_repl / multiagent.run_multi_agent)
      → backends.create_backend(selection) → LLMBackend   harness/backends/
      → tools: parse → dispatch → execute → ToolResult     harness/tools/
```

The router (`models recommend`) **suggests** models; the user chooses one with
`--model`, the menu, or the UI. A model is run at its **native maximum context
window**, automatically capped to what the scanned hardware can hold
(`router/selection.py`).

## Swapping the model or backend (single config seam)

Pointing the agent at a different model or inference server is a
**configuration-only** change — no code edits. Set these in `ci2lab.yaml` (or
the matching `CI2LAB_*` env vars):

```yaml
backend: ollama            # or "openai" for any OpenAI-compatible server
backend_url: http://localhost:11434/v1
model: qwen2.5-coder:7b
```

`config.backend` flows through `pipeline.prepare_session` →
`router.build_model_selection` → `ModelSelection.backend`, and
`backends.create_backend()` selects the matching transport. Adding a brand-new
provider means adding one `LLMBackend` subclass and one entry in
`backends/factory.py`.

## Package map

| Path | Responsibility |
|------|----------------|
| `config.py` | `Ci2LabConfig`; precedence defaults < `ci2lab.yaml` < env < CLI. Defines the `backend` provider seam. |
| `settings.py` | Persisted per-user settings and `ToolSettings`. |
| `console.py` | Shared Rich console (CLI + harness + evals). |
| `pipeline.py` | `prepare_session()`, `build_agent_config()` — glue from config + chosen model to `AgentConfig`. *(mypy strict)* |
| `contracts/types.py` | Shared dataclasses across router and harness: `ModelSpec`, `ModelSelection`, `HardwareProfile`, `IntentResult`. *(mypy strict)* |
| `hardware/profile.py` | RAM/VRAM/GPU scan → `HardwareProfile`; inference-budget math. *(mypy strict)* |
| `router/` | `catalog` (loads `models.json`), `intent` (keyword classifier), `recommend` (scoring), `selection` (`build_model_selection` + context-window cap), `resolve`. *(mypy strict)* |
| `catalog/models.json` | ~86 model entries: tag, VRAM, `tool_mode`, native context window, benchmarks. |
| `runtime/ollama.py` | Ollama process/model queries (`/api/tags`, install paths). |

### `harness/` — the agent engine

| Path | Responsibility |
|------|----------------|
| `backends/` | **Pluggable LLM transports.** `base.LLMBackend` (protocol + shared HTTP plumbing), `ollama.OllamaBackend` (native `/api/chat`, `num_ctx`), `openai_compat.OpenAICompatBackend` (`/v1`, for vLLM/LM Studio/llama.cpp), `factory.create_backend`. *(mypy strict)* |
| `llm_client.py` | Thin backward-compatible facade over `backends` (delegates `chat`/`stream_chat`). |
| `llm_errors.py`, `token_usage.py` | Error classification; token accounting. |
| `query/loop.py` | `run_agent` — the ReAct loop (round → LLM call → parse → execute → nudges). `_prepare_turn_content` handles vision/PDF pre-processing. |
| `query/` (rest) | `llm_io` (stream/non-stream call), `nudges`, `retry_governor`, `verifier`, `session_hooks`. |
| `multiagent/` | Orchestrated roles: `orchestrator` (phase runner), `runner` (subagent invocation), `roles`, `state`, `intent` (deterministic routing), plus the peer-review pipeline: `paper_review`, `grounding`, `manuscript`, `context_budget`. |
| `context/` | `compact` (micro-compact + LLM summary) and `trim` (mechanical history trimming). |
| `tools/` | `registry`/`schemas*` (tool definitions), `parsing*` (model output → `ToolCall`), `dispatch` + `executor*` (run), `capabilities` (read/write/mutating categories), and the implementations (`bash*`, `filesystem*`, `git_tools`, `web`, `vision_tool`, `delegate`, `skill_tool`, `yard_tool`, `todo`, `docx*`, `convert`, `patch`, `notebook`, `inspection`). The five registries are cross-checked by `tests/test_tool_registry_consistency.py`. |
| `prompts/`, `skills/`, `mcp/` | System-prompt assembly; `SKILL.md` loading; MCP stdio client. |
| `yard/` | The Yard: data-driven `COMPONENT.md` salvage-component registry (`loader`) and in-process entrypoint execution with readiness/permission/dependency gates (`runner`), fronted by the single `yard` gateway tool. See [`docs/YARD.md`](YARD.md). |
| `security/` | Per-tool permission and workspace policy (harness side). |
| `repl.py`, `session.py`, `run_logger.py`, `vision.py`, `project_memory.py` | REPL; session persistence; structured run logs; vision helpers; project memory (`CI2LAB.md`/`AGENTS.md`). |

### Other top-level packages

| Path | Responsibility |
|------|----------------|
| `cli/` | The `ci2lab` command: `main` (dispatch), `parser`, `runtime` (CLI → config), `menu`, and `commands/` (`agent`, `chat`, `models`, `doctor`, `hardware`, `sessions`, `skills`, `yard`, `evals`, `ui`). |
| `security/` | Permission engines (`engine`, `policy`, `decisions`, `permissions`), the OpenCode-compatible config layer (`opencode_*`), audit/comparison, and the Claude deterministic/live audit matrices. *(Google-style docstrings)* |
| `ui/` | Local web app: `server` (facade) + `server_parts/` (`http`, `api`, `agent`, `serializers`, `uploads`), `projects`/`researchers` (peer-review state), and `static/` (frontend assets — still Spanish; see `docs/KNOWN_LIMITATIONS.md`). *(Google-style docstrings)* |
| `evals/` | Harness evaluation suite (`run`, `runner`, `task`, `harness_write_eval`). *(Google-style docstrings)* |
| `scripts/` | `audit_live_models`, etc. |

## Tooling & quality gates

```powershell
pip install -e ".[dev]"     # adds ruff + mypy
python -m ruff check ci2lab tests     # lint (passes clean)
python -m ruff format ci2lab tests    # formatter (whole repo formatted)
python -m mypy ci2lab                  # type-check (passes clean)
python -m pytest -q                    # ~905 tests
```

Linting and formatting are configured in `pyproject.toml` (`[tool.ruff]`). The
whole package type-checks at the baseline bar, with the **strict** bar
(`disallow_untyped_defs`) enforced for the core packages listed in
`[[tool.mypy.overrides]]`; that strict list is intended to grow until it covers
the whole package. CI (`.github/workflows/ci.yml`) runs all four gates on
Python 3.11 and 3.12.

## Module ownership

| Module | Owner | Input | Output |
|--------|-------|-------|--------|
| `hardware/` | Router | — | `HardwareProfile` |
| `router/` | Router | prompt, profile | scoring, `build_model_selection()` |
| `pipeline.py` | Integration | config + chosen model | `ModelSelection`, `AgentConfig` |
| `harness/backends/` | Harness | `ModelSelection`, messages | `LLMResponse` / `StreamToken` |
| `harness/query/` | Harness | prompt, selection, config | final answer |
| `harness/tools/` | Harness | `ToolCall` | `ToolResult` |
| `contracts/` | Both | — | shared types |

## Entry points

| Command | Module |
|---------|--------|
| `ci2lab` | `ci2lab.cli:main` |
| `ci2lab-audit-live` | `ci2lab.scripts.audit_live_models:main` |
| `python -m ci2lab.evals.run` | mock/live evals |
