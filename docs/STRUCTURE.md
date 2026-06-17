# IAmultiagentica project structure

All of the **product code** lives inside this folder. The surrounding `Ci2Lab/` workspace only holds reference repos.

```text
Ci2Lab/                              # Workspace (not the Python package)
├── claude-code-main/                # Reference — do NOT touch in production
├── odysseus-dev/
├── opencode-dev/
├── deepagents-main/
│
└── IAmultiagentica/                 # ← PROJECT (this git repo)
    ├── pyproject.toml
    ├── README.md
    ├── COMANDOS.md
    ├── ci2lab/                      # Installable Python package
    │   ├── __init__.py
    │   ├── console.py               # Shared Rich console (CLI + harness + evals)
    │   ├── config.py                # Ci2LabConfig, ci2lab.yaml, env vars
    │   ├── pipeline.py              # prepare_session, build_agent_config
    │   ├── cli/                     # `ci2lab` entrypoint
    │   │   ├── main.py              # Subcommand dispatch
    │   │   ├── parser.py
    │   │   ├── runtime.py           # merge CLI → Ci2LabConfig → AgentConfig
    │   │   └── commands/            # agent, sessions, doctor, hardware, models, evals, ui
    │   ├── contracts/               # Shared types between router and harness
    │   ├── hardware/                # scan_hardware(), inference budget
    │   ├── router/                  # catalog, intent, recommend, selection
    │   ├── catalog/                 # models.json
    │   ├── runtime/                 # ollama.py (ensure-pull still pending)
    │   ├── security/                # Permission engines and audit
    │   ├── harness/
    │   │   ├── query/               # ReAct loop: loop.py, llm_io, nudges, session_hooks
    │   │   ├── context/             # history trim + compaction
    │   │   ├── security/            # Per-tool permissions and workspace policy (harness)
    │   │   ├── tools/               # schemas, dispatch, executor, implementations
    │   │   ├── mcp/                 # MCP client
    │   │   ├── skills/              # SKILL.md loading
    │   │   ├── prompts/             # system.md, fenced_tools.md, compact.md
    │   │   ├── repl.py, session.py, run_logger.py, …
    │   ├── evals/                   # Harness evaluation suite
    │   ├── ui/                      # Local HTTP server + static/
    │   └── scripts/                 # audit_live_models, etc.
    ├── docs/, references/
    ├── evals/tasks/                 # Evaluation JSON
    ├── tests/                       # pytest
    ├── audit/redteam/               # Offensive security runner
    └── runs/                        # Run logs (gitignored)
```

## Module split

| Module | Owner | Input | Output |
|--------|-------|-------|--------|
| `hardware/` | Router | — | `HardwareProfile` |
| `router/` | Router | prompt, profile | scoring, `model_fits()`, `build_model_selection()` |
| `pipeline.py` | Integration | config + chosen model | `ModelSelection`, `AgentConfig` |
| `harness/query/` | Harness | prompt, selection, config | final answer |
| `harness/tools/` | Harness | `ToolCall` | `ToolResult` |
| `contracts/` | Both | — | shared types |

## Data flow

```text
User
  → ci2lab chat | agent | ui
  → cli/runtime: merge_cli_config → Ci2LabConfig
  → pipeline.prepare_session() → ModelSelection
  → pipeline.build_agent_config() → AgentConfig
  → harness.query.run_agent()  (or harness.repl.run_repl)
```

The router (`models recommend`) **suggests** models; the user chooses one with `--model` or in the UI.

## Entry points

| Command | Module |
|---------|--------|
| `ci2lab` | `ci2lab.cli:main` |
| `ci2lab-audit-live` | `ci2lab.scripts.audit_live_models:main` |
| `python -m ci2lab.evals.run` | mock/live evals |

## Local development

```powershell
cd IAmultiagentica
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest -q
```
