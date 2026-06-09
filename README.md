# IAmultiagentica

CLI local que detecta las capacidades del ordenador, elige el modelo open source óptimo y ejecuta un agente con herramientas en terminal (VS Code, PowerShell, CMD).

## Estructura

Todo el código del producto está **aquí**. Los repos de referencia (claude-code, odysseus, opencode, deepagents) están en la carpeta padre `Ci2Lab/` y no forman parte de este paquete.

Ver [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

## Estado actual

El harness agéntico local está **validado y cerrado como hito** (2026-06-09):

- Mock evals: **7/7 PASS**
- Live evals con `llama3.1:8b`: **7/7 PASS**
- Tests automatizados: **64 passed**
- Logging estructurado en `runs/`
- Edición habilitada en modo supervisado (`write_file` / `edit_file` + diff preview)
- `bash` protegido con confirmación + blocklist

Hardware / router / runtime quedan para fases futuras.

Documentación del cierre:

- [Validación live](docs/audits/live_eval_status.md)
- [Limitaciones conocidas](docs/KNOWN_LIMITATIONS.md)
- [Checklist de regresión](docs/regression_checklist.md)
- [Evaluación del arnés](docs/evals.md)
- [Logging en `runs/`](docs/audits/run_logging.md)
- [Política de edición supervisada](docs/WRITE_POLICY.md)
- [Estado write/edit](docs/audits/write_edit_tools_status.md)

## Módulos

| Módulo | Estado | Descripción |
|--------|--------|-------------|
| `ci2lab/contracts/` | ✅ | Contrato router ↔ arnés |
| `ci2lab/hardware/` | 🔲 | Perfilador RAM/VRAM/GPU |
| `ci2lab/router/` | 🔲 | Catálogo + selección de modelo |
| `ci2lab/runtime/` | 🔲 | Ollama pull/ensure |
| `ci2lab/harness/` | ✅ | Arnés completo (ReAct, 7 tools, REPL, sesiones, streaming, run logs) |

## Instalación para usarlo

Requisitos:

- Python 3.11 o superior.
- [Ollama](https://ollama.com/download) instalado y abierto.

### macOS / Linux

```bash
cd IAmultiagentica
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ci2lab doctor
ci2lab models recommend
ci2lab models install qwen2.5-coder-1.5b
ollama pull qwen2.5-coder:1.5b
ci2lab models run qwen2.5-coder-1.5b
```

### Windows PowerShell

```powershell
cd IAmultiagentica
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ci2lab doctor
ci2lab models recommend
ci2lab models install qwen2.5-coder-1.5b
ollama pull qwen2.5-coder:1.5b
ci2lab models run qwen2.5-coder-1.5b
```

`ci2lab models recommend` muestra los modelos permitidos para ese ordenador. El usuario puede pasar a `install` el ID del catálogo (`qwen2.5-coder-1.5b`) o el tag de Ollama (`qwen2.5-coder:1.5b`).

Comandos útiles:

```bash
ci2lab chat                              # modo interactivo agéntico
ci2lab sessions                          # historial guardado
ci2lab "lista los archivos Python" --model qwen2.5-coder-1.5b --yes
```

Cada ejecución guarda artefactos en `runs/` (desactivar con `--no-log`):

```bash
ci2lab --workspace . "lista los archivos"     # log en runs/
ci2lab --no-log "lista los archivos"           # sin carpeta de run
ci2lab --runs-dir ./_runs "hola"               # directorio personalizado
```

Config opcional en `ci2lab.yaml` (modelo, workspace, `runs_dir`, `log_runs`, etc.). Ver [`docs/audits/run_logging.md`](docs/audits/run_logging.md).

`write_file` y `edit_file` están **habilitadas en modo supervisado**: diff preview obligatorio por defecto, aprobación humana, `--yes` no omite el preview. No es edición autónoma ni flujo principal sobre el código crítico del repo. Desactivar con `write_tools_enabled: false` en yaml. Ver [`docs/WRITE_POLICY.md`](docs/WRITE_POLICY.md) y [`docs/audits/write_edit_tools_status.md`](docs/audits/write_edit_tools_status.md).

**Evaluación del arnés** (sin Ollama en modo mock):

```bash
python -m ci2lab.evals.run
ci2lab evals run
```

Ver [`docs/evals.md`](docs/evals.md).

## Documentación

- [Estructura del proyecto](docs/STRUCTURE.md)
- [Validación live del harness](docs/audits/live_eval_status.md)
- [Política de edición supervisada](docs/WRITE_POLICY.md)
- [Limitaciones conocidas](docs/KNOWN_LIMITATIONS.md)
- [Checklist de regresión](docs/regression_checklist.md)
- [Handoff: hardware + router](docs/HARDWARE_ROUTER_HANDOFF.md)
- [Logging de ejecuciones (`runs/`)](docs/audits/run_logging.md)
- [Evaluación del arnés](docs/evals.md)
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
