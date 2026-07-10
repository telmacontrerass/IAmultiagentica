# ci2lab

**CLI agéntico local-first** — detecta las capacidades de tu hardware, recomienda modelos de código abierto que caben en tu máquina y ejecuta un agente ReAct con herramientas en el terminal y en una interfaz web local.

El transporte de inferencia es **enchufable**: Ollama por defecto o cualquier servidor compatible con OpenAI (vLLM, LM Studio, llama.cpp). Cambiar de modelo o backend es solo configuración — no hay que tocar código.

> **Manual extendido:** [`docs/USAGE_MANUAL.md`](docs/USAGE_MANUAL.md) · **Guía de comandos:** [`COMANDOS.md`](COMANDOS.md) · **Estructura:** [`docs/STRUCTURE.md`](docs/STRUCTURE.md)

---

## Qué problema resuelve

La mayoría de los CLI agénticos asumen que tienes acceso a una API cloud o a hardware de gama alta. `ci2lab` resuelve eso en tres pasos:

1. **Perfila tu máquina** — detecta RAM, VRAM y GPU.
2. **Recomienda modelos** — filtra el catálogo de 86 modelos a los que realmente caben en tu hardware.
3. **Ejecuta el agente** — ReAct loop con 28 herramientas integradas, seguridad configurable y logs estructurados.

---

## Estado actual

| Módulo | Estado | Descripción |
|--------|--------|-------------|
| `ci2lab/contracts/` | Estable | Tipos compartidos entre router y harness |
| `ci2lab/hardware/` | Estable | Perfilador RAM/VRAM/GPU/CPU |
| `ci2lab/router/` | Estable | Catálogo, intención, puntuación, `build_model_selection()` |
| `ci2lab/catalog/` | Estable | `models.json` — 86 modelos con VRAM, tool_mode, contexto nativo, benchmarks |
| `ci2lab/pipeline.py` | Estable | `prepare_session()`, `build_agent_config()` (CLI + UI) |
| `ci2lab/harness/backends/` | Estable | Transportes LLM enchufables (Ollama nativo + compatible OpenAI) |
| `ci2lab/harness/` | Estable | Harness ReAct, REPL, sesiones, streaming, logs |
| `ci2lab/harness/query/` | Estable | Loop ReAct (`run_agent`), nudges, streaming LLM |
| `ci2lab/harness/tools/` | Estable | 28 herramientas integradas + MCP dinámico (`mcp__*`) |
| `ci2lab/harness/multiagent/` | Estable | Orquestación de roles + revisión científica entre pares |
| `ci2lab/harness/mcp/` | Estable | Cliente MCP stdio (`.ci2lab/mcp.json`) |
| `ci2lab/harness/skills/` | Estable | Workspace skills (`.ci2lab/skills/*/SKILL.md`) |
| `ci2lab/ui/` | Estable | Interfaz web local en `127.0.0.1:8765` |
| `ci2lab/security/` | Estable | Motores de permisos (`ci2lab`, `ci2lab_guard`, …) |
| `ci2lab/evals/` | Estable | Suite de evaluación del harness (7 tareas, mock + live) |
| `ci2lab/bench/` | Estable | Suite de benchmarks comparativos (no corre en CI) |
| `ci2lab/runtime/` | Pendiente | No hay `ensure_model_ready` — el usuario debe ejecutar `ollama pull` manualmente |
| Web frontend | Limitado | La interfaz web está en español; el agente y el CLI son en inglés |

---

## Arquitectura

```
Usuario
  → ci2lab chat | agent | ui              cli/ , ui/
  → cli/runtime: merge_cli_config          config.py
  → pipeline.prepare_session()             pipeline.py + router/
  → pipeline.build_agent_config()
  → harness.query.run_agent()
      → backends.create_backend()          harness/backends/
      → tools: parse → dispatch → execute  harness/tools/
```

| Carpeta | Responsabilidad |
|---------|----------------|
| `ci2lab/config.py` | `Ci2LabConfig`; precedencia: defaults < `ci2lab.yaml` < env < CLI |
| `ci2lab/pipeline.py` | Puente entre configuración, modelo elegido y `AgentConfig` |
| `ci2lab/contracts/` | Tipos compartidos: `ModelSpec`, `ModelSelection`, `HardwareProfile` |
| `ci2lab/hardware/` | Escaneo RAM/VRAM/GPU → `HardwareProfile` |
| `ci2lab/router/` | Catálogo, clasificador de intención, puntuación, selección |
| `ci2lab/catalog/` | `models.json` con 86 modelos |
| `ci2lab/harness/` | Motor ReAct: backends, loop, herramientas, contexto, multiagente |
| `ci2lab/security/` | Motores de permisos, reglas deny/ask/allow, auditorías |
| `ci2lab/ui/` | Servidor web local con proyectos de conocimiento |
| `ci2lab/evals/` | Evaluación de comportamiento del harness |
| `ci2lab/bench/` | Benchmarks comparativos contra otros CLI agénticos |
| `ci2lab/cli/` | Comando `ci2lab` y todos sus subcomandos |

Para el mapa completo: [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

---

## Requisitos

- **Python 3.11 o 3.12** (3.13 no verificado)
- **[Ollama](https://ollama.com/download)** instalado y corriendo (para el modo por defecto)
- Al menos **4 GB de RAM** libre para el modelo más pequeño; 8+ GB recomendados
- Sistema operativo: Windows, macOS, Linux (ver notas de instalación)

Dependencias Python principales: `rich`, `httpx`, `psutil`, `pypdf`, `pymupdf`, `prompt_toolkit`, `sympy`, `openpyxl`, `ddgs`.

---

## Instalación

### Windows PowerShell (recomendado)

```powershell
cd IAmultiagentica
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

> Si el proyecto está en OneDrive, excluye `.venv/` de la sincronización.

También hay un script de instalación automática:

```powershell
.\instalar.ps1
```

### macOS / Linux

```bash
cd IAmultiagentica
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Instalar Ollama

```powershell
# Windows
irm https://ollama.com/install.ps1 | iex

# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh
```

### Verificar la instalación

```powershell
ci2lab doctor
```

Comprueba el paquete, la conexión a Ollama y los requisitos básicos.

---

## Configuración

### Variables de entorno principales

| Variable | Efecto |
|----------|--------|
| `CI2LAB_MODEL` | Modelo por defecto |
| `CI2LAB_BACKEND` | `ollama` (default) o `openai` |
| `CI2LAB_BACKEND_URL` | URL del servidor (OpenAI-compatible) |
| `CI2LAB_OLLAMA_URL` | URL base de Ollama |
| `CI2LAB_TOOL_MODE` | `native` o `fenced` |
| `CI2LAB_MAX_ROUNDS` | Máximo de rondas del loop ReAct |
| `CI2LAB_WORKSPACE` | Directorio de trabajo del agente |
| `CI2LAB_NO_LOG` | `1` para deshabilitar logs |
| `CI2LAB_RUNS_DIR` | Directorio de artefactos de log |
| `CI2LAB_AUTO_CONFIRM` / `CI2LAB_YES` | `1` para auto-confirmar herramientas peligrosas |
| `CI2LAB_WRITE_TOOLS_ENABLED` | `false` para deshabilitar escritura |
| `CI2LAB_STREAM` | `false` para deshabilitar streaming |

### Archivo de configuración `ci2lab.yaml`

Créalo en la raíz del proyecto o en `~/.ci2lab/ci2lab.yaml`:

```yaml
model: qwen2.5-coder:7b
backend: ollama
backend_url: http://localhost:11434/v1
workspace: .
max_rounds: 25
stream: true
auto_confirm: false
log_runs: true
runs_dir: runs
write_tools_enabled: true
require_diff_preview: true
tool_mode: native   # o "fenced"
```

### Extensiones de workspace

| Recurso | Ubicación | Para qué sirve |
|---------|-----------|----------------|
| Skills | `.ci2lab/skills/<nombre>/SKILL.md` | Comandos `/nombre` en el REPL |
| MCP | `.ci2lab/mcp.json` | Servidores de herramientas externos |
| Memoria del proyecto | `CI2LAB.md`, `AGENTS.md` | Instrucciones persistentes inyectadas en el prompt |
| Hooks | `.ci2lab/hooks.json` | Hooks `before_tool`, `after_tool`, `after_final_answer` |

---

## Uso rápido

### 1. Detectar hardware y elegir modelo

```powershell
ci2lab hardware
ci2lab models recommend "programa en Python"
ollama pull qwen2.5-coder:7b
```

### 2. Iniciar el agente

```powershell
# Menú interactivo
ci2lab

# REPL con un modelo concreto
ci2lab --model qwen2.5-coder:7b chat

# Petición única
ci2lab --model qwen2.5-coder:7b "lista los archivos Python"

# Interfaz web
ci2lab ui
```

### 3. Cambiar de backend (ejemplo: LM Studio)

```powershell
$env:CI2LAB_BACKEND = "openai"
$env:CI2LAB_BACKEND_URL = "http://localhost:1234/v1"
ci2lab --model mi-modelo chat
```

---

## Comandos principales

Los flags globales van **antes** del subcomando: `ci2lab --model X chat`, no `ci2lab chat --model X`.

| Comando | Descripción |
|---------|-------------|
| `ci2lab doctor` | Diagnóstico del entorno |
| `ci2lab hardware` | Perfil de hardware |
| `ci2lab hardware --json` | Hardware como JSON |
| `ci2lab models recommend` | Recomendaciones por hardware |
| `ci2lab models recommend "tarea"` | Recomendaciones por tarea e intención |
| `ci2lab models install <id>` | Instrucciones para instalar un modelo |
| `ci2lab models run <id>` | Abre el modelo con `ollama run` |
| `ci2lab chat` | REPL interactivo (carga sesiones) |
| `ci2lab agent "petición"` | Una sola petición al agente |
| `ci2lab menu` | Menú interactivo de inicio |
| `ci2lab ui` | Interfaz web en `http://127.0.0.1:8765` |
| `ci2lab sessions` | Lista de sesiones guardadas |
| `ci2lab skills` | Gestión de skills de workspace |
| `ci2lab evals run` | Evaluación del harness (mock, sin Ollama) |
| `ci2lab evals run --live` | Evaluación con Ollama real |
| `ci2lab bench run --agent ci2lab` | Benchmark comparativo (requiere Ollama) |
| `ci2lab permissions` | Gestión de permisos |
| `ci2lab-audit-live` | Auditoría en vivo de modelos |

Flags útiles:

| Flag | Efecto |
|------|--------|
| `--model <id>` | Modelo a usar |
| `--tool-mode native\|fenced` | Modo de llamada a herramientas |
| `--workspace <ruta>` | Directorio de trabajo del agente |
| `--yes` | Auto-confirmar herramientas peligrosas |
| `--no-stream` | Deshabilitar streaming |
| `--no-log` | No guardar artefactos en `runs/` |
| `--max-rounds <n>` | Límite de rondas del loop |
| `--session <id>` | Reanudar una sesión |
| `--security-engine <nombre>` | Motor de seguridad a usar |

Para la referencia completa: [`COMANDOS.md`](COMANDOS.md).

---

## Tests

```powershell
# Suite completa (~905 tests)
python -m pytest -q

# Un archivo concreto
python -m pytest tests/test_bash_safety.py -q

# Un test concreto
python -m pytest tests/test_tool_registry_consistency.py::test_tool_names_in_dispatch -q
```

CI ejecuta las cuatro puertas de calidad en Python 3.11 y 3.12:

```powershell
python -m ruff check ci2lab tests      # lint
python -m ruff format ci2lab tests     # formato
python -m mypy ci2lab                   # tipos (strict en el núcleo)
python -m pytest -q                     # tests
```

---

## Benchmarks y evaluaciones

### Evaluación del harness (mock, sin Ollama)

```powershell
ci2lab evals run                        # mock — no requiere Ollama
ci2lab evals run --live --model llama3.1:8b   # con Ollama real
ci2lab evals run --task 004_block_dangerous_bash   # tarea concreta
python -m ci2lab.evals.run             # equivalente desde Python
```

Los 7 tasks incluidos verifican: uso de herramientas, bloqueo de bash peligroso, edición supervisada y deshabilitación de escritura. Ver [`docs/evals.md`](docs/evals.md).

### Benchmarks comparativos (live, no están en CI)

```powershell
# Solo ci2lab
ci2lab bench run --agent ci2lab --model qwen2.5-coder:32b --samples 5

# Smoke H3 (ci2lab vs ci2lab-multi)
ci2lab bench run \
  --tasks-dir benchmarks/tasks/h3_smoke \
  --results-dir benchmarks/results/h3_smoke \
  --agent ci2lab --agent ci2lab-multi \
  --model qwen2.5-coder:32b --samples 1

# Tarea concreta
ci2lab bench run --agent ci2lab --task cli-01 --task bug-01
```

Los resultados van a `benchmarks/results/<timestamp>/` como `results.jsonl` y `summary.json`. Ver [`benchmarks/README.md`](benchmarks/README.md) y [`docs/BENCHMARKING.md`](docs/BENCHMARKING.md).

---

## Seguridad

### Motores de seguridad

| Motor | Comportamiento |
|-------|---------------|
| **`ci2lab_guard`** (default) | Guards duros + capa deny/ask/allow + aprobaciones de sesión |
| `ci2lab` | Legado: guards duros + confirmación `[y/N]` (sin reglas deny/ask/allow) |
| `opencode_experimental` | **INSEGURO / solo laboratorio** — sin guards duros |

```powershell
ci2lab chat                                         # ci2lab_guard (default)
ci2lab --security-engine ci2lab chat                # motor legado
ci2lab --security-engine opencode_experimental chat # INSEGURO — solo comparativa
```

### Perfiles de seguridad

| Perfil | `write_file`/`edit_file` | `bash` | Default |
|--------|--------------------------|--------|---------|
| `strict` | Bloqueado | Bloqueado | — |
| `standard` | Supervisado | Lista negra + confirmación | **Sí** |
| `dev` | Como standard | Como standard (límites más altos) | — |
| `audit` | Bloqueado | Bloqueado | — |

Política completa: [`docs/SECURITY_POLICY.md`](docs/SECURITY_POLICY.md).

### Scripts de auditoría

```powershell
ci2lab-audit-live
python scripts/audit_ci2lab_guard_live.py --all
python scripts/compare_security_engines.py
python scripts/security_gate_check.py --workspace . --tool bash --target "rm file.txt"
```

**Antes de limpiar o mover carpetas:** haz una auditoría no destructiva con `audit/` y `scripts/` para entender el contenido. Muchas carpetas contienen trabajo de investigación o histórico que no debe borrarse sin revisión.

---

## Estructura del repositorio

| Carpeta / Archivo | Propósito |
|-------------------|-----------|
| `ci2lab/` | Paquete Python principal — todo el código del producto |
| `tests/` | Suite de tests (~905 tests, 92 archivos) |
| `evals/` | Definiciones de tareas de evaluación del harness (JSON) |
| `benchmarks/` | Tareas, resultados y precios para benchmarks comparativos |
| `docs/` | Documentación técnica (estructura, seguridad, benchmarking, etc.) |
| `scripts/` | Scripts de utilidad: auditorías, comparativas de seguridad, exportación |
| `audit/` | Directorio de auditorías de seguridad (redteam, reportes, sandbox) |
| `runs/` | Artefactos de ejecución generados por el agente (git-ignored) |
| `references/` | Repositorios de referencia (claude-code, odysseus, opencode, deepagents) — solo lectura, no son parte del paquete |
| `Examenes/` | PDFs de ejemplo / casos de uso — no son parte del paquete |
| `.ci2lab/` | Configuración local del usuario (skills, MCP, sesiones) |
| `.agents/` | Directorio de trabajo de agentes en ejecución |
| `COMANDOS.md` | Guía práctica de comandos en español |
| `CHANGELOG.md` | Historial de cambios |
| `CONTRIBUTING.md` | Guía de contribución y estándares de código |
| `instalar.ps1` / `instalar.sh` / `instalar.bat` | Scripts de instalación automática |
| `pyproject.toml` | Configuración del proyecto, dependencias, lint, tipos |

---

## Desarrollo y contribución

```powershell
# Entorno de desarrollo
pip install -e ".[dev]"

# Cuatro puertas de calidad (deben pasar antes de cualquier commit)
python -m ruff check ci2lab tests
python -m ruff format ci2lab tests
python -m mypy ci2lab
python -m pytest -q
```

Estándares clave:
- Docstrings estilo Google en todos los módulos, clases y funciones públicas.
- Tipos en todas las firmas; `mypy ci2lab` debe pasar.
- Al añadir una herramienta: actualizar `TOOL_NAMES`, `DISPATCH`, el esquema JSON y la categoría de capabilities. El test `tests/test_tool_registry_consistency.py` falla si hay desincronización.
- Al añadir un backend: implementar `LLMBackend` y registrar en `backends/factory.py`. Nada más cambia.
- Los módulos fachada (re-exportan internos) están exentos de F401 — no dejes que `ruff --fix` los limpie.
- No toques el loop ReAct (`harness/query/loop.py`) sin leer los comentarios; el timing de nudges/rondas es frágil.

Ver [`CONTRIBUTING.md`](CONTRIBUTING.md) para el flujo completo.

---

## Troubleshooting

| Síntoma | Causa probable | Solución |
|---------|---------------|----------|
| `ci2lab: command not found` | Entorno virtual no activado o paquete no instalado | Activar `.venv` y ejecutar `pip install -e ".[dev]"` |
| `Connection refused` al conectar con Ollama | Ollama no está corriendo | Ejecutar `ollama serve` |
| `model not found` al iniciar el agente | El modelo no está descargado | Ejecutar `ollama pull <tag>` |
| El agente usa `fenced` en vez de `native` | Modelo no catalogado o sin tool_mode | Pasar `--tool-mode native` explícitamente |
| `ci2lab agent --session` no carga historial | Limitación conocida | Usar `ci2lab chat --session <id>` para reanudar |
| Tests fallan en Windows con paths | Separador de rutas | Revisar que no haya `\` hardcodeados en fixtures |
| Mypy falla en módulos nuevos | Falta de anotaciones de tipo | Añadir tipos a todas las firmas del módulo |
| El frontend web está en español | Limitación conocida | Ver [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) |
| `ruff --fix` elimina imports en `__init__.py` | Son re-exportaciones intencionales | Añadir el fichero a `per-file-ignores` en `pyproject.toml` |

---

## Documentación adicional

| Documento | Contenido |
|-----------|-----------|
| [`docs/USAGE_MANUAL.md`](docs/USAGE_MANUAL.md) | Manual extendido de uso — todos los flujos con detalle |
| [`COMANDOS.md`](COMANDOS.md) | Referencia práctica de comandos (instalación → uso diario) |
| [`docs/STRUCTURE.md`](docs/STRUCTURE.md) | Mapa de módulos y flujo de datos |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Estándares de código y flujo de contribución |
| [`CHANGELOG.md`](CHANGELOG.md) | Historial de cambios |
| [`docs/SECURITY_POLICY.md`](docs/SECURITY_POLICY.md) | Política de seguridad y perfiles |
| [`docs/WRITE_POLICY.md`](docs/WRITE_POLICY.md) | Política de edición supervisada |
| [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) | Limitaciones conocidas |
| [`docs/BENCHMARKING.md`](docs/BENCHMARKING.md) | Metodología de benchmarks |
| [`docs/evals.md`](docs/evals.md) | Evaluación del harness |
| [`docs/PEER_REVIEW.md`](docs/PEER_REVIEW.md) | Flujo de revisión entre pares |
| [`docs/TOOLS_ROADMAP.md`](docs/TOOLS_ROADMAP.md) | Roadmap de herramientas |

---

## Licencia

Publicado bajo la [Licencia MIT](LICENSE).

---

## Workspace de referencia

```text
Ci2Lab/
  IAmultiagentica/     ← este proyecto (paquete ci2lab)
  claude-code-main/    ← referencia — no es parte del paquete
  odysseus-dev/        ← referencia
  opencode-dev/        ← referencia
  deepagents-main/     ← referencia
```

Los repositorios en `Ci2Lab/` fuera de `IAmultiagentica/` son solo lectura para estudio y comparativa. El código del paquete instalable vive únicamente en `ci2lab/`.
