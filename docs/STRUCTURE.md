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
    ├── ci2lab.yaml                  # Config opcional (no versionado por defecto)
    ├── ci2lab/                      # Paquete Python instalable
    │   ├── contracts/               # Tipos compartidos router ↔ arnés
    │   ├── hardware/                # Perfilador de sistema (profile.py)
    │   ├── router/                  # Intención, catálogo, scoring, resolve
    │   ├── catalog/                 # models.json
    │   ├── runtime/                 # Vacío (ensure_model pendiente)
    │   ├── harness/                 # Arnés agéntico (ReAct + tools)
    │   ├── evals/                   # Tareas de evaluación del arnés
    │   ├── config.py                # Config centralizada (yaml + env + CLI)
    │   ├── cli.py                   # CLI principal
    │   └── pipeline.py              # Integración router ↔ arnés (parcial)
    ├── docs/
    ├── references/                  # Notas de extracción (no código externo)
    ├── runs/                        # Logs de ejecución (gitignored)
    └── tests/
```

## División de módulos

| Módulo | Responsable lógico | Entrada | Salida |
|--------|-------------------|---------|--------|
| `hardware/` | Router | — | `HardwareProfile` |
| `router/` | Router | `user_prompt`, `HardwareProfile` | `ModelSelection` |
| `runtime/` | Router | `ModelSelection` | modelo listo en Ollama (pendiente) |
| `harness/` | Arnés | `user_prompt`, `ModelSelection` | acciones + respuesta |
| `contracts/` | Ambos | — | tipos compartidos |

## Flujo de datos

```text
Usuario
  │
  ├─ ci2lab hardware ──────────────► hardware.scan_hardware() ──► tabla CLI
  │
  ├─ ci2lab models recommend ──────► router.recommend / resolve ──► tabla CLI
  │
  └─ ci2lab chat / agent ──────────► pipeline.prepare_session()
                                        │
                                        ├─ (ideal) scan_hardware + resolve_model
                                        │            + ensure_model_ready
                                        │
                                        └─ (actual) default_selection() fallback
                                              │
                                              ▼
                                        harness.run_agent() / run_repl()
```

### Gap de integración actual

`pipeline.py` intenta importar `ci2lab.hardware.profiler` y `ci2lab.runtime.ensure`, que no existen. El `ImportError` hace que `chat` y `agent` usen siempre `default_selection()` con el tag de `--model` o `llama3.1:8b`, sin pasar por el router ni el catálogo.

Los comandos `hardware` y `models` **sí** llaman directamente a `hardware/` y `router/`.

## Integración (objetivo)

```python
from ci2lab.pipeline import prepare_session
from ci2lab.harness import run_agent

profile, selection = prepare_session("write a Python script", force_model=None)
run_agent("write a Python script", selection, hardware=profile)
```

Cuando `pipeline.py` esté corregido, `selection` incluirá `tool_mode`, `supports_tools` y `context_length` del catálogo.

## Desarrollo local

```powershell
cd IAmultiagentica
py -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows
pip install -e ".[dev]"
python -m pytest -q
```
