# Ci2Lab — Guía de comandos

Chuleta práctica con todos los comandos del proyecto, de instalación a scripts avanzados.

> **Guía rápida:** [`README.md`](README.md) · **Manual extendido:** [`docs/USAGE_MANUAL.md`](docs/USAGE_MANUAL.md)

---

## Índice rápido

1. [Instalación](#1-instalación)
2. [Diagnóstico del entorno](#2-diagnóstico-del-entorno)
3. [Modelos](#3-modelos)
4. [Uso básico](#4-uso-básico)
5. [Agente single-agent](#5-agente-single-agent)
6. [Multiagente](#6-multiagente)
7. [UI local](#7-ui-local)
8. [Sesiones](#8-sesiones)
9. [Tests y calidad](#9-tests-y-calidad)
10. [Evaluaciones del harness](#10-evaluaciones-del-harness)
11. [Benchmarks](#11-benchmarks)
12. [Seguridad](#12-seguridad)
13. [Scripts útiles](#13-scripts-útiles)
14. [Troubleshooting rápido](#14-troubleshooting-rápido)

---

## 1. Instalación

> `ci2lab` requiere Python 3.11 o 3.12 y [Ollama](https://ollama.com/download).

### Automática (recomendada en Windows)

```powershell
.\instalar.ps1
```

El script comprueba Python, instala Ollama si falta, crea el entorno virtual, instala las dependencias y registra `ci2lab` en el PATH del usuario.

### Manual — Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Si PowerShell bloquea la ejecución del script de activación:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\.venv\Scripts\Activate.ps1
```

### Manual — macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Dependencias opcionales

```powershell
# Conversión pdf_to_docx (requiere pdf2docx)
pip install -e ".[convert]"

# Solo producción, sin herramientas de desarrollo
pip install -e "."
```

### Instalar Ollama por separado

```powershell
# Windows
irm https://ollama.com/install.ps1 | iex

# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh
```

---

## 2. Diagnóstico del entorno

```powershell
ci2lab doctor
```

Verifica el paquete, Python, Ollama y la configuración básica. Ejecutar siempre que algo falle.

```powershell
ci2lab hardware
```

Muestra RAM, VRAM, GPU y CPU detectados.

```powershell
ci2lab hardware --json
```

Lo mismo en formato JSON parseable.

```powershell
ollama --version
```

Confirma que Ollama está instalado y en el PATH.

```powershell
ollama list
```

Lista los modelos descargados en Ollama.

```powershell
ollama serve
```

Inicia Ollama si no está corriendo como servicio en segundo plano.

---

## 3. Modelos

### Recomendar modelos

```powershell
ci2lab models recommend
```

Recomienda modelos que caben en tu hardware (RAM/VRAM detectada).

```powershell
ci2lab models recommend "programa en Python"
ci2lab models recommend "razonamiento complejo"
ci2lab models recommend "documentos largos"
ci2lab models recommend "máquina con pocos recursos"
```

Filtra además por intención/tarea.

```powershell
ci2lab models recommend --limit 3
```

Limita el número de resultados.

### Instalar y gestionar modelos

```powershell
ci2lab models install <MODEL_ID>
```

Muestra el plan de instalación (qué `ollama pull` ejecutar). No descarga por sí solo.

```powershell
ollama pull qwen2.5-coder:7b
```

Descarga el modelo en Ollama. Sustituye el tag por el que recomiende `models recommend`.

```powershell
ci2lab models run <MODEL_ID>
```

Abre el modelo directamente con `ollama run` para pruebas rápidas sin el harness.

```powershell
ollama rm qwen2.5-coder:7b
```

Elimina el modelo del disco.

### Referencia de IDs

`ci2lab` acepta el ID del catálogo (`qwen2.5-coder-7b`) o el tag de Ollama (`qwen2.5-coder:7b`). Para los comandos `ollama`, usa siempre el tag de Ollama.

Ejemplo: si `models recommend` sugiere `qwen2.5-coder-7b`, el tag de Ollama es `qwen2.5-coder:7b`.

| Tier | RAM aprox. | Ejemplos |
|------|-----------|----------|
| edge | 2–5 GB | `llama3.2:1b`, `qwen2.5-coder:1.5b`, `phi3:mini` |
| workstation | 6–16 GB | `qwen2.5-coder:7b`, `llama3:8b`, `phi4:14b` |
| enterprise | 25 GB+ | `qwen2.5-coder:32b`, `llama3.1:70b` |

---

## 4. Uso básico

> Los flags globales van **antes** del subcomando: `ci2lab --model X chat`, **no** `ci2lab chat --model X`.

```powershell
ci2lab
```

Abre el menú interactivo de inicio (elige modo, modelo y workspace de forma guiada).

```powershell
ci2lab menu
```

Equivalente explícito al anterior.

```powershell
ci2lab chat
```

Abre el REPL interactivo con el modelo por defecto.

```powershell
ci2lab --model qwen2.5-coder:7b chat
```

REPL con un modelo concreto.

```powershell
ci2lab --model qwen2.5-coder:7b "lista los archivos Python"
```

Petición única al agente.

```powershell
ci2lab --workspace . chat
```

Fija el directorio de trabajo del agente.

```powershell
ci2lab --max-rounds 10 --model qwen2.5-coder:7b chat
```

Limita el número de rondas del loop ReAct.

### Para salir del REPL

Escribe cualquiera de: `/exit`, `/quit`, `exit`, `quit` o pulsa `Ctrl+C`.

---

## 5. Agente single-agent

### Flags globales más útiles

| Flag | Efecto |
|------|--------|
| `--model <id-o-tag>` | Modelo a usar |
| `--workspace <ruta>` | Directorio de trabajo del agente |
| `--cwd <ruta>` | Alias legado de `--workspace` |
| `--tool-mode native\|fenced` | Formato de llamadas a herramientas |
| `--yes` | Auto-confirmar herramientas peligrosas |
| `--no-stream` | Deshabilitar streaming |
| `--no-log` | No guardar artefactos en `runs/` |
| `--runs-dir <ruta>` | Directorio alternativo de artefactos |
| `--max-rounds <n>` | Límite de rondas del loop |
| `--session <id>` | Reanudar o usar una sesión concreta |
| `--security-engine <nombre>` | Motor de seguridad |

### Ejemplos

```powershell
# Petición única con el subcomando explícito
ci2lab agent "lista los archivos Python"

# Con modelo y workspace
ci2lab --model qwen2.5-coder:7b --workspace . agent "resume el README"

# Sin streaming ni log, auto-confirmando
ci2lab --no-log --no-stream --yes --model qwen2.5-coder:7b "lista los archivos"

# Limitar rondas y cambiar el directorio de logs
ci2lab --max-rounds 5 --runs-dir ./_runs --model qwen2.5-coder:7b chat

# Con motor de seguridad legado
ci2lab --security-engine ci2lab --model qwen2.5-coder:7b chat

# Tool mode explícito
ci2lab --tool-mode native --model qwen2.5-coder:7b chat
ci2lab --tool-mode fenced --model qwen2.5-coder:7b chat

# Deshabilitar logs via entorno
$env:CI2LAB_NO_LOG = "1"
ci2lab --model qwen2.5-coder:7b chat
```

### Variables de entorno equivalentes

```powershell
$env:CI2LAB_MODEL         = "qwen2.5-coder:7b"
$env:CI2LAB_BACKEND       = "ollama"              # o "openai"
$env:CI2LAB_BACKEND_URL   = "http://localhost:11434/v1"
$env:CI2LAB_OLLAMA_URL    = "http://localhost:11434"
$env:CI2LAB_TOOL_MODE     = "native"
$env:CI2LAB_MAX_ROUNDS    = "25"
$env:CI2LAB_WORKSPACE     = "."
$env:CI2LAB_NO_LOG        = "1"
$env:CI2LAB_RUNS_DIR      = "./_runs"
$env:CI2LAB_STREAM        = "false"
$env:CI2LAB_YES           = "1"                   # auto-confirm
$env:CI2LAB_WRITE_TOOLS_ENABLED = "false"         # solo lectura
```

### Backend alternativo (vLLM, LM Studio, llama.cpp)

```powershell
$env:CI2LAB_BACKEND     = "openai"
$env:CI2LAB_BACKEND_URL = "http://localhost:8000/v1"   # ajusta el puerto
ci2lab --model nombre-de-tu-modelo chat
```

---

## 6. Multiagente

> **Verifica antes** que el flag está disponible en tu checkout:
> ```powershell
> ci2lab --help
> ```
> Si `--multi-agent` no aparece, el orquestador no está presente en este checkout. Ver nota más abajo.

```powershell
ci2lab --multi-agent --model qwen2.5-coder:7b chat
```

Activa el orquestador de subagentes secuenciales (`harness/multiagent/`).

> **Nota experimental:** El subsistema multiagente (`harness/multiagent/`) está implementado, pero el flag `--multi-agent` puede no estar presente en todos los checkouts. El orquestador de roles, la revisión científica entre pares y el presupuesto de contexto por subagente sí están en el código. Consulta [`docs/USAGE_MANUAL.md`](docs/USAGE_MANUAL.md) para más detalle.

---

## 7. UI local

```powershell
ci2lab ui
```

Inicia el servidor web local y abre el navegador en `http://127.0.0.1:8765`.

```powershell
ci2lab --model qwen2.5-coder:7b ui
```

UI con un modelo por defecto concreto.

```powershell
ci2lab ui --no-open
```

Inicia el servidor sin abrir el navegador automáticamente.

```powershell
ci2lab ui --port 8766
```

Puerto alternativo (útil si 8765 está ocupado).

> La UI corre solo localmente. Los proyectos de conocimiento se guardan en `~/.ci2lab/projects/<id>/`. El texto de la interfaz está en español (limitación conocida).

---

## 8. Sesiones

```powershell
ci2lab sessions
```

Lista las sesiones guardadas con ID, fecha y resumen.

```powershell
ci2lab sessions --json
```

Lo mismo en formato JSON.

```powershell
ci2lab --model qwen2.5-coder:7b --session <SESSION_ID> chat
```

Reanuda una sesión existente (con historial). El `--session` carga el historial solo en modo `chat`, no en `agent`.

### Eliminar una sesión

```powershell
# Windows PowerShell
Remove-Item "$HOME\.ci2lab\sessions\<SESSION_ID>.json"

# macOS / Linux
rm ~/.ci2lab/sessions/<SESSION_ID>.json
```

---

## 9. Tests y calidad

### Suite de tests

```powershell
python -m pytest -q
```

Ejecuta los ~905 tests. Debe pasar limpia antes de cualquier commit o merge.

```powershell
python -m pytest tests/test_bash_safety.py -q
```

Un archivo concreto.

```powershell
python -m pytest -k "test_tool_registry" -q
```

Todos los tests cuyo nombre contiene `test_tool_registry`.

```powershell
python -m pytest --lf -q
```

Solo los tests que fallaron en la última ejecución.

```powershell
python -m pytest -v tests/test_multiagent_orchestrator.py
```

Con detalles de cada test (útil al depurar).

```powershell
python -m pytest -s tests/test_config.py
```

Con output de `print` visible.

```powershell
python -m pytest -q --ignore=tests/redteam
```

Ignora los tests de red team (más lentos, pensados para ejecución manual).

### Puertas de calidad (CI)

Las cuatro deben pasar antes de cualquier commit. CI las ejecuta en Python 3.11 y 3.12.

```powershell
python -m ruff check ci2lab tests      # lint
python -m ruff format ci2lab tests     # formato (modifica archivos)
python -m mypy ci2lab                   # tipos (strict en el núcleo)
python -m pytest -q                     # tests
```

Comprobar formato sin modificar:

```powershell
python -m ruff format --check ci2lab tests
```

---

## 10. Evaluaciones del harness

Verifican que el harness usa las herramientas correctamente y respeta la seguridad y configuración. **No son benchmarks de calidad de modelo.** No requieren Ollama en modo mock.

### Mock (sin Ollama, determinista)

```powershell
ci2lab evals run
python -m ci2lab.evals.run
```

### Live (con Ollama real)

```powershell
ci2lab evals run --live
ci2lab evals run --live --model llama3.1:8b
python -m ci2lab.evals.run --live --model llama3.1:8b
```

### Tarea concreta

```powershell
ci2lab evals run --task 004_block_dangerous_bash
ci2lab evals run --task 005_edit_file_denied --task 006_edit_file_approved
python -m ci2lab.evals.run --task 001_list_files
```

### Directorio de tareas alternativo

```powershell
ci2lab evals run --tasks-dir ./mis_tareas
```

### Tareas incluidas

| ID | Qué verifica |
|----|-------------|
| `001_list_files` | El agente usa `ls` |
| `002_read_file` | El agente usa `read_file` |
| `003_find_function` | El agente usa `grep` o `glob`+`read_file` |
| `004_block_dangerous_bash` | Comandos peligrosos son bloqueados |
| `005_edit_file_denied` | Edición supervisada rechazada — archivo sin cambios |
| `006_edit_file_approved` | Edición supervisada aprobada — archivo modificado |
| `007_write_tools_disabled` | `write_tools_enabled=false` bloquea escritura |

Resultado en `evals/results/<timestamp>/`: `summary.json` y `results.jsonl`.

Código de salida: `0` si todas pasan, `1` si alguna falla.

---

## 11. Benchmarks

Miden calidad real del agente en tareas de código. **Corren en live** (necesitan Ollama). **Nunca corren en CI.**

> **Antes de ejecutar:** asegúrate de que el modelo elegido está descargado (`ollama list`). Si todos los runs fallan en 2–3 segundos, el campo `tokens` aparece como `"-"` en `results.jsonl` y no se generan artefactos — indica que el modelo no está instalado o que el agente no se invocó correctamente.

### Solo ci2lab

```powershell
ci2lab bench run --agent ci2lab --model <tu-modelo-instalado> --samples 5
python -m ci2lab.bench.run --agent ci2lab --model <tu-modelo-instalado>
```

### ci2lab vs ci2lab-multi (H3 smoke — recomendado para primer run)

```powershell
ci2lab bench run `
  --tasks-dir benchmarks/tasks/h3_smoke `
  --results-dir benchmarks/results/h3_smoke `
  --agent ci2lab --agent ci2lab-multi `
  --model <tu-modelo-instalado> --samples 1
```

### Tareas concretas

```powershell
ci2lab bench run --agent ci2lab --model <tu-modelo-instalado> --task cli-01 --task bug-01
```

### Matriz completa (requiere Claude Code y Codex configurados)

```powershell
ci2lab bench run `
  --agent ci2lab --agent ci2lab-multi --agent claude-code --agent codex `
  --model <tu-modelo-instalado> --samples 5
```

### Directorio de resultados alternativo

```powershell
ci2lab bench run --agent ci2lab --model <tu-modelo-instalado> `
  --results-dir benchmarks/results/mi-run
```

### Resultados

Los artefactos se guardan en `benchmarks/results/<timestamp>/`:

| Archivo | Contenido |
|---------|-----------|
| `results.jsonl` | Una fila por tarea × agente × muestra |
| `summary.json` | Pass@1, Pass@k, tokens medios, coste USD, latencia mediana |

Ver [`benchmarks/README.md`](benchmarks/README.md) y [`docs/BENCHMARKING.md`](docs/BENCHMARKING.md).

---

## 12. Seguridad

### Antes de aprobar cualquier operación con el agente

```powershell
git status
git diff
```

Revisar el estado del repo antes de que el agente haga cambios.

### Verificar qué haría una herramienta (dry-run de seguridad)

```powershell
python scripts/security_gate_check.py --workspace . --tool bash --target "rm archivo.txt"
```

Evalúa la puerta de seguridad sin ejecutar nada. Acepta `--engine`, `--security-profile` y `--permission-config`.

```powershell
# Con motor específico
python scripts/security_gate_check.py --engine ci2lab --workspace . --tool bash --target "cat /etc/passwd"

# Con perfil de seguridad
python scripts/security_gate_check.py --security-profile strict --workspace . --tool write_file --target "output.txt"
```

### Comparar motores de seguridad

```powershell
python scripts/compare_security_engines.py --workspace .
```

Compara decisiones de `ci2lab` vs `opencode_experimental` sobre una matriz de casos.

### Auditoría determinista (sin LLM)

```powershell
python scripts/audit_claude_deterministic.py
```

Ejecuta la matriz de decisiones de `claude_experimental` sin invocar ningún modelo. Los artefactos se guardan en `audit/deterministic_claude/<timestamp>/`.

### Auditoría live (con Ollama)

```powershell
# Todos los modelos por defecto (llama3.1:8b native + qwen3:4b fenced)
python scripts/audit_claude_experimental_live.py --all

# Un modelo concreto
python scripts/audit_claude_experimental_live.py --model llama3.1:8b --tool-mode native
```

Requiere que los modelos estén descargados en Ollama. Los artefactos van a `audit/live_claude/<timestamp>/`.

```powershell
# Equivalente via entrypoint del paquete
ci2lab-audit-live
```

### Motores de seguridad disponibles

```powershell
ci2lab chat                                          # claude_experimental (default)
ci2lab --security-engine ci2lab chat                 # legado: solo [y/N], sin reglas
ci2lab --security-engine opencode_experimental chat  # INSEGURO — solo laboratorio
```

---

## 13. Scripts útiles

Todos los scripts están en `scripts/` y se pueden ejecutar con el entorno virtual activado. Se pasan a Python directamente — no son entrypoints del paquete (excepto `ci2lab-audit-live`).

### Seguridad y auditoría

| Script | Para qué sirve | Comando | Estado |
|--------|----------------|---------|--------|
| `scripts/security_gate_check.py` | Evalúa la puerta de seguridad sin ejecutar la herramienta (dry-run) | `python scripts/security_gate_check.py --workspace . --tool bash --target "rm x"` | Estable |
| `scripts/compare_security_engines.py` | Compara decisiones ci2lab vs opencode_experimental | `python scripts/compare_security_engines.py --workspace .` | Estable |
| `scripts/audit_claude_deterministic.py` | Auditoría determinista de claude_experimental sin LLM | `python scripts/audit_claude_deterministic.py` | Estable |
| `scripts/audit_claude_experimental_live.py` | Auditoría live con modelos Ollama reales | `python scripts/audit_claude_experimental_live.py --all` | Estable |

### Configuración de seguridad

| Script | Para qué sirve | Comando | Estado |
|--------|----------------|---------|--------|
| `scripts/security_config_export.py` | Exporta configuraciones de permisos desde preset o archivo | `python scripts/security_config_export.py --preset opencode_dev` | Experimental |
| `scripts/compare_opencode_configs.py` | Compara varias configs de OpenCode contra una matriz de casos | `python scripts/compare_opencode_configs.py --preset opencode_paranoid` | Experimental |

### Evaluaciones live

| Script | Para qué sirve | Comando | Estado |
|--------|----------------|---------|--------|
| `scripts/run_harness_write_eval.py` | Eval de fiabilidad de escritura del harness con modelos reales (P2.10) | `python scripts/run_harness_write_eval.py --models llama3.1:8b` | Estable |

### Notas

- `compare_opencode_configs.py` requiere al menos un `--config <ruta.json>` o `--preset <nombre>`.
- `security_config_export.py` requiere `--preset <nombre>` o `--input <ruta.json>`.
- Los artefactos de los scripts de auditoría van a `audit/` por defecto; se puede cambiar con `--output-root`.

---

## 14. Troubleshooting rápido

| Síntoma | Causa más probable | Solución |
|---------|-------------------|----------|
| `ci2lab: command not found` | Entorno virtual no activado o paquete no instalado | Activar `.venv` con `Activate.ps1` y ejecutar `pip install -e ".[dev]"` |
| `Connection refused` al iniciar el agente | Ollama no está corriendo | Ejecutar `ollama serve` |
| `model not found` al iniciar el agente | Modelo no descargado | Ejecutar `ollama pull <tag>` |
| PowerShell bloquea `Activate.ps1` | Política de ejecución de scripts | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| Benchmark falla en 2–3 s, tokens = `"-"` | Modelo no está instalado o tag incorrecto | Verificar con `ollama list`; el tag debe coincidir exactamente |
| El agente usa `fenced` aunque el modelo soporta `native` | Modelo no catalogado o ID no reconocido | Pasar `--tool-mode native` explícitamente |
| `ci2lab agent --session <id>` no carga historial | Limitación conocida | Usar `ci2lab --session <id> chat` en su lugar |
| `test_tool_registry_consistency` falla | Herramienta añadida sin actualizar los 5 registros | Actualizar `TOOL_NAMES`, `DISPATCH`, schema, `capabilities` e implementación |
| `ruff --fix` elimina imports de `__init__.py` | Re-exportaciones intencionales (F401) | Añadir el fichero a `per-file-ignores` en `pyproject.toml` |
| `mypy` falla en módulo nuevo | Falta de anotaciones de tipo | Añadir tipos a todas las firmas del módulo |
| Tests fallan con paths en Windows | Separadores de ruta | Ver `tests/test_bash_windows_vectors.py` para los vectores específicos |
| Puerto 8765 en uso al lanzar UI | Otro proceso ocupa el puerto | `ci2lab ui --port 8766` |
| La interfaz web está en español | Limitación conocida | Ver [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) |
| `security_config_export.py` sin args | Requiere `--preset` o `--input` | `python scripts/security_config_export.py --preset opencode_dev` |
| `compare_opencode_configs.py` sin args | Requiere `--config` o `--preset` | `python scripts/compare_opencode_configs.py --preset opencode_paranoid` |

---

## Secuencia recomendada desde cero

```powershell
# 1. Entrar en el proyecto y preparar el entorno
cd IAmultiagentica
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 2. Instalar Ollama (si no lo tienes)
irm https://ollama.com/install.ps1 | iex
ollama --version

# 3. Verificar el entorno
ci2lab doctor

# 4. Detectar hardware y elegir modelo
ci2lab hardware
ci2lab models recommend "programa en Python"

# 5. Descargar el modelo elegido
ollama pull <tag-del-modelo-elegido>

# 6. Primer uso
ci2lab --model <id-o-tag> chat
```
