# Estructura del proyecto IAmultiagentica

Todo el **código del producto** vive dentro de esta carpeta. El workspace `Ci2Lab/` alrededor solo contiene repos de referencia.

```text
Ci2Lab/                              # Workspace (no es el paquete Python)
├── claude-code-main/                # Referencia — NO tocar en producción
├── odysseus-dev/
├── opencode-dev/
├── deepagents-main/
│
└── IAmultiagentica/                 # ← PROYECTO (este repo git)
    ├── pyproject.toml
    ├── README.md
    ├── COMANDOS.md
    ├── ci2lab/                      # Paquete Python instalable
    │   ├── __init__.py
    │   ├── console.py               # Consola Rich compartida (CLI + arnés + evals)
    │   ├── config.py                # Ci2LabConfig, ci2lab.yaml, env vars
    │   ├── pipeline.py              # prepare_session, build_agent_config
    │   ├── cli/                     # Entrypoint `ci2lab`
    │   │   ├── main.py              # Despacho de subcomandos
    │   │   ├── parser.py
    │   │   ├── runtime.py           # merge CLI → Ci2LabConfig → AgentConfig
    │   │   └── commands/            # agent, sessions, doctor, hardware, models, evals, ui
    │   ├── contracts/               # Tipos compartidos router ↔ arnés
    │   ├── hardware/                # scan_hardware(), presupuesto inferencia
    │   ├── router/                  # catálogo, intención, recommend, selection
    │   ├── catalog/                 # models.json
    │   ├── runtime/                 # ollama.py (ensure pull pendiente)
    │   ├── security/                # Motores de permisos y audit
    │   ├── harness/
    │   │   ├── query/               # Bucle ReAct: loop.py, llm_io, nudges, session_hooks
    │   │   ├── context/             # trim + compactación de historial
    │   │   ├── security/            # Permisos por tool y política workspace (arnés)
    │   │   ├── tools/               # schemas, dispatch, executor, implementaciones
    │   │   ├── mcp/                 # Cliente MCP
    │   │   ├── skills/              # Carga de SKILL.md
    │   │   ├── prompts/             # system.md, fenced_tools.md, compact.md
    │   │   ├── repl.py, session.py, run_logger.py, …
    │   ├── evals/                   # Suite de evaluación del arnés
    │   ├── ui/                      # Servidor HTTP local + static/
    │   └── scripts/                 # audit_live_models, etc.
    ├── docs/, references/
    ├── evals/tasks/                 # JSON de evaluación
    ├── tests/                       # pytest
    ├── audit/redteam/               # Runner ofensivo de seguridad
    └── runs/                        # Logs de ejecución (gitignored)
```

## División de módulos

| Módulo | Responsable | Entrada | Salida |
|--------|-------------|---------|--------|
| `hardware/` | Router | — | `HardwareProfile` |
| `router/` | Router | prompt, perfil | scoring, `model_fits()`, `build_model_selection()` |
| `pipeline.py` | Integración | config + modelo elegido | `ModelSelection`, `AgentConfig` |
| `harness/query/` | Arnés | prompt, selección, config | respuesta final |
| `harness/tools/` | Arnés | `ToolCall` | `ToolResult` |
| `contracts/` | Ambos | — | tipos compartidos |

## Flujo de datos

```text
Usuario
  → ci2lab chat | agent | ui
  → cli/runtime: merge_cli_config → Ci2LabConfig
  → pipeline.prepare_session() → ModelSelection
  → pipeline.build_agent_config() → AgentConfig
  → harness.query.run_agent()  (o harness.repl.run_repl)
```

El router (`models recommend`) **sugiere** modelos; el usuario elige con `--model` o la UI.

## Puntos de entrada

| Comando | Módulo |
|---------|--------|
| `ci2lab` | `ci2lab.cli:main` |
| `ci2lab-audit-live` | `ci2lab.scripts.audit_live_models:main` |
| `python -m ci2lab.evals.run` | evals mock/live |

## Desarrollo local

```powershell
cd IAmultiagentica
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest -q
```
