# IAmultiagentica

A local CLI that detects your computer's capabilities, recommends open-source models that fit your hardware, and runs a tool-using agent in the terminal (VS Code, PowerShell, CMD).

It also includes a local web interface (`ci2lab ui`), workspace skills, an MCP client, and optional project memory.

## Structure

All of the product code lives **here**. The reference repos (claude-code, odysseus, opencode, deepagents) sit in the parent `Ci2Lab/` folder and are not part of this package.

See [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

## Current status

| Module | Status | Description |
|--------|--------|-------------|
| `ci2lab/contracts/` | Done | Shared types between router and harness |
| `ci2lab/hardware/` | Done | RAM/VRAM/GPU/CPU profiler (`ci2lab hardware`) |
| `ci2lab/router/` | Done | Catalog, intent, scoring, `model_fits()` |
| `ci2lab/catalog/` | Done | `models.json` — 64 models with VRAM, tool_mode, benchmarks |
| `ci2lab/pipeline.py` | Done | `prepare_session()`, `build_agent_config()` (CLI + UI) |
| `ci2lab/harness/` | Done | ReAct harness, REPL, sessions, streaming, run logs |
| `ci2lab/harness/query/` | Done | ReAct loop (`run_agent`), nudges, LLM streaming |
| `ci2lab/harness/tools/` | Done | 25 built-in tools + dynamic MCP (`mcp__*`) |
| `ci2lab/harness/mcp/` | Done | MCP stdio client (`.ci2lab/mcp.json`) |
| `ci2lab/harness/skills/` | Done | Workspace skills (`.ci2lab/skills/*/SKILL.md`) |
| `ci2lab/ui/` | Done | Local web interface at `127.0.0.1:8765` |
| `ci2lab/security/` | Done | Permission engines (`ci2lab`, `claude_experimental`, …) |
| `ci2lab/runtime/` | Pending | No `ensure_model_ready` — no automatic `ollama pull` |

### Harness

- **25 built-in tools**: reading, writing, bash, git, web, notebook, skills, MCP, etc.
- Structured logging under `runs/`
- Supervised editing (`write_file` / `edit_file` / `write_docx` + diff preview)
- Context compaction (micro-compact + LLM summary + trim)
- Project memory: `CI2LAB.md`, `AGENTS.md` in the workspace
- The agent loop is **task-agnostic**: no per-topic special cases. Robustness comes from generic mechanisms only — loop detection, an error-streak cutoff, workspace-policy handling, edit follow-ups, a `web_fetch`→`web_search` redirect, and a few recovery nudges.
- Agent system prompt and tool outputs are in **English** (the terminal/CLI UI is English; the web frontend is still Spanish — see [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md)).

### Router and hardware

- `ci2lab hardware` — system scan
- `ci2lab models recommend` — recommendations by intent and VRAM/RAM
- `ci2lab models install <id>` — pull/run/chat commands
- `ci2lab models run <id>` — open the model with `ollama run`

The router **suggests** models; you choose which one to run with `--model`. When `chat`/`agent`/UI start, `pipeline.prepare_session()` applies the `tool_mode` from the catalog (override with `--tool-mode`). See [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md).

### Security engines

| Engine | Role |
|--------|------|
| **`claude_experimental`** (default) | Hard guards + a `deny`/`ask`/`allow` layer, modern prompt, session approvals |
| **`ci2lab`** | Legacy: hard guards + `[y/N]` confirmation only (no deny/ask/allow rules) |
| **`opencode_experimental`** | Unsafe lab (no hard guards) — for comparison with OpenCode only |

```powershell
# Default: claude_experimental (deny/ask/allow + hard guards)
ci2lab chat

# Legacy, without a rule-based permission layer
ci2lab --security-engine ci2lab chat

# Unsafe lab — do not use for real work
ci2lab --security-engine opencode_experimental chat
```

Validation: [`docs/CLAUDE_EXPERIMENTAL_VALIDATION.md`](docs/CLAUDE_EXPERIMENTAL_VALIDATION.md) · Policy: [`docs/SECURITY_POLICY.md`](docs/SECURITY_POLICY.md)

```powershell
ci2lab-audit-live                                    # live model audit
python scripts/audit_claude_experimental_live.py --all
python scripts/compare_security_engines.py
python scripts/security_gate_check.py --workspace . --tool bash --target "rm file.txt"
```

## Installation

Requirements: Python 3.11+, [Ollama](https://ollama.com/download) running.

### Windows PowerShell

```powershell
cd IAmultiagentica
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ci2lab doctor
ci2lab hardware
ci2lab models recommend
```

> **Note:** If the project lives in OneDrive, avoid syncing `.venv/`.

### macOS / Linux

```bash
cd IAmultiagentica
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ci2lab doctor
```

### Download and try a model

```powershell
ollama pull qwen2.5-coder:7b
ci2lab --model qwen2.5-coder:7b chat
```

## Using the agent

```powershell
ci2lab doctor
ci2lab hardware
ci2lab models recommend
ci2lab                                                 # menu interactivo inicial
ci2lab menu                                            # abrir el selector manualmente
ci2lab ui                                              # http://127.0.0.1:8765
ci2lab --model qwen2.5-coder:7b chat                   # REPL (loads sessions)
ci2lab --model llama3.1:8b "list the Python files"     # one turn
ci2lab sessions
```

**Global flags** go **before** the subcommand: `ci2lab --model X chat` (not `ci2lab chat --model X`).

### Workspace extensions

| Resource | Location | Use |
|----------|----------|-----|
| Skills | `.ci2lab/skills/<name>/SKILL.md` | `/skill-name` commands in the REPL |
| MCP | `.ci2lab/mcp.json` | External tool servers |
| Project memory | `CI2LAB.md`, `AGENTS.md` | Persistent instructions injected into the prompt |

### Tool modes (`tool_mode`)

Each catalog model defines `native` or `fenced`. Override: `--tool-mode fenced`.

### Logging under `runs/`

```powershell
ci2lab --workspace . "list the files"     # logs under runs/
ci2lab --no-log "list the files"
```

Optional config: `ci2lab.yaml`. See [`docs/audits/run_logging.md`](docs/audits/run_logging.md).

### Supervised editing

See [`docs/WRITE_POLICY.md`](docs/WRITE_POLICY.md).

### Harness evaluation

```bash
python -m ci2lab.evals.run    # mock, no Ollama
ci2lab evals run --live       # requires Ollama
```

See [`docs/evals.md`](docs/evals.md).

## Documentation

- [Project structure](docs/STRUCTURE.md)
- [Commands (practical guide)](COMANDOS.md)
- [Hardware + router handoff](docs/HARDWARE_ROUTER_HANDOFF.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
- [Tools roadmap](docs/TOOLS_ROADMAP.md)
- [Supervised editing policy](docs/WRITE_POLICY.md)
- [Regression checklist](docs/regression_checklist.md)
- [Harness evaluation](docs/evals.md)

## Workspace

```text
Ci2Lab/
  IAmultiagentica/     ← this project
  claude-code-main/    ← reference only
  odysseus-dev/
  opencode-dev/
  deepagents-main/
```
