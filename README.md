# IAmultiagentica

CLI local que detecta las capacidades del ordenador, recomienda modelos open source que quepan en tu hardware y ejecuta un agente con herramientas en terminal (VS Code, PowerShell, CMD).

## Estructura

Todo el código del producto está **aquí**. Los repos de referencia (claude-code, odysseus, opencode, deepagents) están en la carpeta padre `Ci2Lab/` y no forman parte de este paquete.

Ver [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

## Estado actual (2026-06-10)

| Módulo | Estado | Descripción |
|--------|--------|-------------|
| `ci2lab/contracts/` | ✅ | Tipos compartidos router ↔ arnés |
| `ci2lab/hardware/` | ✅ | Perfilador RAM/VRAM/GPU/CPU (CLI `ci2lab hardware`) |
| `ci2lab/router/` | ✅ | Catálogo, intención, scoring y selección de modelo (CLI `ci2lab models …`) |
| `ci2lab/catalog/` | ✅ | `models.json` con 21 modelos y metadatos (VRAM, tool_mode, benchmarks) |
| `ci2lab/harness/` | ✅ | Arnés ReAct, 7 tools, REPL, sesiones, streaming, run logs |
| `ci2lab/runtime/` | 🔲 | Sin `ensure_model_ready` — no hay `ollama pull` automático |
| Integración pipeline | ⚠️ | `chat`/`agent` aún no usan el router (ver [Limitaciones](docs/KNOWN_LIMITATIONS.md)) |

### Harness (validado 2026-06-09)

- Mock evals: **7/7 PASS**
- Live evals con `llama3.1:8b`: **7/7 PASS**
- Tests automatizados: **70 passed**
- Logging estructurado en `runs/`
- Edición supervisada (`write_file` / `edit_file` + diff preview)
- `bash` con confirmación + blocklist
- System prompts del agente en **inglés** (mejor compatibilidad con modelos locales)

### Router y hardware (implementados, uso parcial)

- `ci2lab hardware` — escaneo del sistema
- `ci2lab models recommend` — recomendaciones por intención y VRAM/RAM
- `ci2lab models install <id>` — comandos para pull/run/chat
- `ci2lab models run <id>` — abre el modelo con `ollama run`

El router **no está conectado** al flujo `ci2lab chat` / `ci2lab agent` todavía: `pipeline.py` cae en un fallback porque faltan imports de integración (`runtime.ensure`). Ver [`docs/HARDWARE_ROUTER_HANDOFF.md`](docs/HARDWARE_ROUTER_HANDOFF.md#estado-de-implementación-2026-06-10).

## Instalación

Requisitos:

- Python 3.11 o superior
- [Ollama](https://ollama.com/download) instalado y en marcha

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

> **Nota:** Si el proyecto está en OneDrive, evita sincronizar `.venv/` (miles de archivos pequeños; puede corromper el entorno).

### macOS / Linux

```bash
cd IAmultiagentica
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ci2lab doctor
ci2lab hardware
ci2lab models recommend
```

### Descargar y probar un modelo

```powershell
ollama pull qwen2.5-coder:7b
ci2lab models install qwen2.5-coder-7b    # muestra comandos
ci2lab --model qwen2.5-coder:7b chat      # agente interactivo
```

`ci2lab models recommend` muestra modelos que caben en tu equipo. Puedes usar el ID del catálogo (`qwen2.5-coder-7b`) o el tag Ollama (`qwen2.5-coder:7b`).

## Uso del agente

### Comandos principales

```powershell
ci2lab doctor                                          # comprobar entorno
ci2lab hardware                                        # perfil de hardware
ci2lab models recommend                                # modelos recomendados
ci2lab --model qwen2.5-coder:7b chat                   # REPL agéntico
ci2lab --model llama3.1:8b "lista los archivos Python" # una petición
ci2lab sessions                                        # sesiones guardadas
```

**Importante:** los flags globales (`--model`, `--tool-mode`, `--yes`, etc.) van **antes** del subcomando:

```powershell
# Correcto
ci2lab --model qwen2.5-coder:7b --tool-mode fenced chat

# Incorrecto (falla)
ci2lab chat --model qwen2.5-coder:7b
```

### Modos de herramientas (`tool_mode`)

| Modo | Cuándo usarlo |
|------|----------------|
| `native` (default) | Modelos con function calling fiable vía Ollama (`llama3.1:8b`, `qwen2.5-coder:7b`) |
| `fenced` | Modelos que responden mejor con bloques de texto (`deepseek-coder`, modelos pequeños) |

Si el modelo imprime JSON o código pero no ejecuta herramientas, prueba:

```powershell
ci2lab --model qwen2.5-coder:7b --tool-mode fenced chat
```

El modelo validado en live evals es `llama3.1:8b`. Otros modelos pueden comportarse distinto en tool use.

### Logging en `runs/`

Cada ejecución guarda artefactos en `runs/` (desactivar con `--no-log`):

```powershell
ci2lab --workspace . "lista los archivos"     # log en runs/
ci2lab --no-log "lista los archivos"           # sin carpeta de run
ci2lab --runs-dir ./_runs "hola"               # directorio personalizado
```

Config opcional en `ci2lab.yaml` (modelo, workspace, `runs_dir`, `log_runs`, etc.). Ver [`docs/audits/run_logging.md`](docs/audits/run_logging.md).

### Edición supervisada

`write_file` y `edit_file` están habilitadas en modo supervisado: diff preview obligatorio por defecto, aprobación humana; `--yes` no omite el preview. Desactivar con `write_tools_enabled: false` en yaml. Ver [`docs/WRITE_POLICY.md`](docs/WRITE_POLICY.md).

### Evaluación del arnés

```bash
python -m ci2lab.evals.run    # mock, sin Ollama
ci2lab evals run              # equivalente
ci2lab evals run --live       # requiere Ollama
```

Ver [`docs/evals.md`](docs/evals.md).

## Documentación

- [Estructura del proyecto](docs/STRUCTURE.md)
- [Handoff hardware + router](docs/HARDWARE_ROUTER_HANDOFF.md) (especificación e estado de implementación)
- [Limitaciones conocidas](docs/KNOWN_LIMITATIONS.md)
- [Validación live del harness](docs/audits/live_eval_status.md)
- [Política de edición supervisada](docs/WRITE_POLICY.md)
- [Checklist de regresión](docs/regression_checklist.md)
- [Evaluación del arnés](docs/evals.md)
- [Logging en `runs/`](docs/audits/run_logging.md)
- [Pruebas manuales](docs/manual_tests.md)
- [Repos externos de referencia](references/EXTERNAL_REPOS.md)

## Workspace

```text
Ci2Lab/
  IAmultiagentica/     ← este proyecto
  claude-code-main/    ← solo referencia
  odysseus-dev/
  opencode-dev/
  deepagents-main/
```
