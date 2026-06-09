# Estructura del proyecto IAmultiagentica

Todo el **código del producto** vive dentro de esta carpeta. El workspace `Ci2Lab/` alrededor solo contiene repos de referencia.

```text
Ci2Lab/                              # Workspace (no es el paquete Python)
├── claude-code-main/                # Referencia — NO tocar en producción
├── odysseus-dev/
├── opencode-dev/
├── deepagents-main/
├── README.md                        # Índice del workspace
│
└── IAmultiagentica/                 # ← PROYECTO (este repo git)
    ├── pyproject.toml
    ├── README.md
    ├── ci2lab/                      # Paquete Python instalable
    │   ├── contracts/               # 🤝 Compartido router ↔ arnés
    │   ├── hardware/                # Perfilador de sistema
    │   ├── router/                  # Intención + selección de modelo
    │   ├── runtime/                 # Ollama pull/ensure
    │   ├── catalog/                 # models.json, benchmarks.json
    │   ├── harness/                 # Arnés agéntico (ReAct + tools)
    │   ├── config/
    │   ├── cli.py
    │   └── pipeline.py
    ├── docs/
    ├── references/                  # Notas de extracción (no código externo)
    └── tests/
```

## División de trabajo

| Módulo | Responsable | Entrada | Salida |
|--------|-------------|---------|--------|
| `hardware/` + `router/` + `runtime/` | Router | `user_prompt` | `ModelSelection` |
| `harness/` | Arnés | `user_prompt`, `ModelSelection` | acciones + respuesta |
| `contracts/` | Ambos | — | tipos compartidos |

## Integración

```python
from ci2lab.pipeline import prepare_session
from ci2lab.harness.loop import run_agent

profile, selection = prepare_session("programar muy bien")
await run_agent("programar muy bien", selection=selection, hardware=profile)
```

## Desarrollo local

```bash
cd IAmultiagentica
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
```
