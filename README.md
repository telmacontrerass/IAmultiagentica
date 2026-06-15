# IAmultiagentica

CLI local que detecta las capacidades del ordenador, recomienda modelos open source que quepan en tu hardware y ejecuta un agente con herramientas en terminal (VS Code, PowerShell, CMD).

Incluye interfaz web local (`ci2lab ui`), skills de workspace, cliente MCP y memoria de proyecto opcional.

## Estructura

Todo el código del producto está **aquí**. Los repos de referencia (claude-code, odysseus, opencode, deepagents) están en la carpeta padre `Ci2Lab/` y no forman parte de este paquete.

Ver [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

## Estado actual (2026-06-12)

| Módulo | Estado | Descripción |
|--------|--------|-------------|
| `ci2lab/contracts/` | ✅ | Tipos compartidos router ↔ arnés |
| `ci2lab/hardware/` | ✅ | Perfilador RAM/VRAM/GPU/CPU (`ci2lab hardware`) |
| `ci2lab/router/` | ✅ | Catálogo, intención, scoring, `model_fits()` |
| `ci2lab/catalog/` | ✅ | `models.json` — 21 modelos con VRAM, tool_mode, benchmarks |
| `ci2lab/pipeline.py` | ✅ | `prepare_session()`, `build_agent_config()` (CLI + UI) |
| `ci2lab/harness/` | ✅ | Arnés ReAct, REPL, sesiones, streaming, run logs |
| `ci2lab/harness/query/` | ✅ | Bucle ReAct (`run_agent`), nudges, streaming LLM |
| `ci2lab/harness/tools/` | ✅ | 22 herramientas built-in + MCP dinámico (`mcp__*`) |
| `ci2lab/harness/mcp/` | ✅ | Cliente MCP stdio (`.ci2lab/mcp.json`) |
| `ci2lab/harness/skills/` | ✅ | Skills workspace (`.ci2lab/skills/*/SKILL.md`) |
| `ci2lab/ui/` | ✅ | Interfaz web local en `127.0.0.1:8765` |
| `ci2lab/security/` | ✅ | Motores de permisos (`ci2lab`, `claude_experimental`, …) |
| `ci2lab/runtime/` | 🔲 | Sin `ensure_model_ready` — no hay `ollama pull` automático |

### Harness

- **22 herramientas** built-in: lectura, escritura, bash, git, web, notebook, skills, MCP, etc.
- Mock evals: **7/7 PASS** · Live evals (`llama3.1:8b`): **7/7 PASS**
- Tests automatizados: **562 passed** (`python -m pytest -q`)
- Logging estructurado en `runs/`
- Edición supervisada (`write_file` / `edit_file` / `write_docx` + diff preview)
- Compactación de contexto (micro-compact + resumen LLM + trim)
- Project memory: `CI2LAB.md`, `AGENTS.md` en el workspace
- System prompts del agente en **inglés** (mejor compatibilidad con modelos locales)

### Router y hardware

- `ci2lab hardware` — escaneo del sistema
- `ci2lab models recommend` — recomendaciones por intención y VRAM/RAM
- `ci2lab models install <id>` — comandos para pull/run/chat
- `ci2lab models run <id>` — abre el modelo con `ollama run`

El router **sugiere** modelos; tú eliges cuál ejecutar con `--model`. Al arrancar `chat`/`agent`/UI, `pipeline.prepare_session()` aplica el `tool_mode` del catálogo (override con `--tool-mode`). Ver [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md).

### Motores de seguridad

| Motor | Rol |
|-------|-----|
| **`claude_experimental`** (default) | Hard guards + capa `deny`/`ask`/`allow`, prompt moderno, session approvals |
| **`ci2lab`** | Legacy: solo hard guards + confirmación `[s/N]` (sin reglas deny/ask/allow) |
| **`opencode_experimental`** | Laboratorio inseguro (sin hard guards) — solo comparar con OpenCode |

```powershell
# Default: claude_experimental (deny/ask/allow + hard guards)
ci2lab chat

# Legacy sin capa de permisos por reglas
ci2lab --security-engine ci2lab chat

# Laboratorio inseguro — no usar en trabajo real
ci2lab --security-engine opencode_experimental chat
```

Validación: [`docs/CLAUDE_EXPERIMENTAL_VALIDATION.md`](docs/CLAUDE_EXPERIMENTAL_VALIDATION.md) · Política: [`docs/SECURITY_POLICY.md`](docs/SECURITY_POLICY.md)

```powershell
ci2lab-audit-live                                    # auditoría live de modelos
python scripts/audit_claude_experimental_live.py --all
python scripts/compare_security_engines.py
python scripts/security_gate_check.py --workspace . --tool bash --target "rm archivo.txt"
```

## Instalación

Requisitos: Python 3.11+, [Ollama](https://ollama.com/download) en marcha.

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

> **Nota:** Si el proyecto está en OneDrive, evita sincronizar `.venv/`.

### macOS / Linux

```bash
cd IAmultiagentica
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ci2lab doctor
```

### Descargar y probar un modelo

```powershell
ollama pull qwen2.5-coder:7b
ci2lab --model qwen2.5-coder:7b chat
```

## Uso del agente

```powershell
ci2lab doctor
ci2lab hardware
ci2lab models recommend
ci2lab ui                                              # http://127.0.0.1:8765
ci2lab --model qwen2.5-coder:7b chat                   # REPL (carga sesiones)
ci2lab --model llama3.1:8b "lista los archivos Python" # un turno
ci2lab sessions
```

**Flags globales** van **antes** del subcomando: `ci2lab --model X chat` (no `ci2lab chat --model X`).

### Extensiones de workspace

| Recurso | Ubicación | Uso |
|---------|-----------|-----|
| Skills | `.ci2lab/skills/<nombre>/SKILL.md` | Comandos `/skill-name` en REPL |
| MCP | `.ci2lab/mcp.json` | Servidores de herramientas externos |
| Project memory | `CI2LAB.md`, `AGENTS.md` | Instrucciones persistentes en el prompt |

### Modos de herramientas (`tool_mode`)

Cada modelo del catálogo define `native` o `fenced`. Override: `--tool-mode fenced`.

### Logging en `runs/`

```powershell
ci2lab --workspace . "lista los archivos"     # log en runs/
ci2lab --no-log "lista los archivos"
```

Config opcional: `ci2lab.yaml`. Ver [`docs/audits/run_logging.md`](docs/audits/run_logging.md).

### Edición supervisada

Ver [`docs/WRITE_POLICY.md`](docs/WRITE_POLICY.md).

### Evaluación del arnés

```bash
python -m ci2lab.evals.run    # mock, sin Ollama
ci2lab evals run --live       # requiere Ollama
```

Ver [`docs/evals.md`](docs/evals.md).

## Documentación

- [Estructura del proyecto](docs/STRUCTURE.md)
- [Comandos (guía práctica)](COMANDOS.md)
- [Handoff hardware + router](docs/HARDWARE_ROUTER_HANDOFF.md)
- [Limitaciones conocidas](docs/KNOWN_LIMITATIONS.md)
- [Hoja de ruta de herramientas](docs/TOOLS_ROADMAP.md)
- [Política de edición supervisada](docs/WRITE_POLICY.md)
- [Checklist de regresión](docs/regression_checklist.md)
- [Evaluación del arnés](docs/evals.md)

## Workspace

```text
Ci2Lab/
  IAmultiagentica/     ← este proyecto
  claude-code-main/    ← solo referencia
  odysseus-dev/
  opencode-dev/
  deepagents-main/
```
