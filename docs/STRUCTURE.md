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
    ├── ci2lab/                      # Paquete Python instalable
    │   ├── cli/                     # CLI (parser, runtime, commands/*)
    │   ├── contracts/               # Tipos compartidos router ↔ arnés
    │   ├── hardware/                # Perfilador de sistema
    │   ├── router/                  # Intención, catálogo, scoring
    │   ├── catalog/                 # models.json
    │   ├── runtime/                 # ollama.py (ensure pull pendiente)
    │   ├── harness/
    │   │   ├── query/               # Bucle ReAct (loop, nudges, llm_io)
    │   │   ├── context/             # trim + compactación
    │   │   ├── security/            # permisos y política workspace
    │   │   ├── tools/               # schemas, dispatch, executor + tools/*
    │   │   ├── mcp/, skills/, prompts/
    │   ├── evals/, ui/, scripts/
    │   ├── config.py, pipeline.py
    ├── docs/, references/
    ├── evals/tasks/                 # JSON de evaluación
    ├── tests/                       # pytest (+ fixtures/redteam_sandbox)
    ├── audit/redteam/               # runner ofensivo (regenera sandbox)
    └── runs/                        # Logs (gitignored)
```

## División de módulos

| Módulo | Responsable | Entrada | Salida |
|--------|-------------|---------|--------|
| `hardware/` | Router | — | `HardwareProfile` |
| `router/` | Router | prompt, perfil | `ModelSelection` |
| `runtime/` | Router | tag Ollama | `fetch_installed_models` |
| `harness/query/` | Arnés | prompt, selección | respuesta final |
| `harness/tools/` | Arnés | `ToolCall` | `ToolResult` |
| `contracts/` | Ambos | — | tipos compartidos |

## Flujo de datos

```text
Usuario → ci2lab chat/agent → pipeline.prepare_session()
         → harness.query.run_agent() / repl
```

El router (`models recommend`) **sugiere** modelos; el usuario elige con `--model`.

## Desarrollo local

```powershell
cd IAmultiagentica
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest -q
```
