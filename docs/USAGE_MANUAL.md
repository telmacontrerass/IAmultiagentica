# Manual de uso — ci2lab

Guía extendida para el equipo. Cubre todos los flujos, configuración avanzada, interpretación de resultados, buenas prácticas y troubleshooting detallado.

Para el inicio rápido: [`README.md`](../README.md) · Para comandos: [`COMANDOS.md`](../COMANDOS.md).

---

## Índice

1. [Visión general del proyecto](#1-visión-general-del-proyecto)
2. [Glosario de conceptos internos](#2-glosario-de-conceptos-internos)
3. [Arquitectura detallada](#3-arquitectura-detallada)
4. [Instalación paso a paso](#4-instalación-paso-a-paso)
5. [Flujos de uso principales](#5-flujos-de-uso-principales)
6. [Comandos disponibles](#6-comandos-disponibles)
7. [Configuración avanzada](#7-configuración-avanzada)
8. [Ejecución de tests](#8-ejecución-de-tests)
9. [Ejecución de benchmarks y evaluaciones](#9-ejecución-de-benchmarks-y-evaluaciones)
10. [Interpretación de outputs, logs y resultados](#10-interpretación-de-outputs-logs-y-resultados)
11. [Buenas prácticas de desarrollo](#11-buenas-prácticas-de-desarrollo)
12. [Buenas prácticas de seguridad](#12-buenas-prácticas-de-seguridad)
13. [Cómo añadir nuevos módulos y extensiones](#13-cómo-añadir-nuevos-módulos-y-extensiones)
14. [Auditoría no destructiva antes de limpiar carpetas](#14-auditoría-no-destructiva-antes-de-limpiar-carpetas)
15. [Partes experimentales o históricas](#15-partes-experimentales-o-históricas)
16. [Preguntas frecuentes y troubleshooting](#16-preguntas-frecuentes-y-troubleshooting)

---

## 1. Visión general del proyecto

`ci2lab` es un CLI agéntico local-first. El objetivo es que cualquier persona con un portátil moderno pueda correr un agente de IA capaz con modelos de código abierto, sin necesidad de API cloud ni de GPU de gama alta.

El proyecto resuelve tres problemas concretos:

**1. Selección de modelo.** Con 86 modelos en el catálogo y hardware muy variado entre miembros del equipo, el router perfila la máquina y filtra qué modelos caben. La recomendación también considera la tarea (coding, reasoning, documentos largos, edge).

**2. Ejecución del agente.** Un loop ReAct con 28 herramientas integradas corre localmente contra Ollama. El loop es task-agnostic — la robustez viene de mecanismos genéricos (detección de loops, streak de errores, nudges de recuperación), no de casos especiales por tema.

**3. Seguridad configurable.** Tres motores de seguridad y cuatro perfiles permiten ajustar la permisividad desde "solo lectura" (`strict`) hasta "máxima permisividad de desarrollo" (`dev`), con reglas deny/ask/allow por herramienta en el motor por defecto.

---

## 2. Glosario de conceptos internos

| Término | Significado |
|---------|-------------|
| **ReAct loop** | Patrón Reasoning + Acting: el modelo razona, llama a herramientas, observa resultados, repite hasta completar la tarea o alcanzar el límite de rondas. |
| **Backend / transporte** | La capa que habla con el servidor de inferencia. Actualmente: `OllamaBackend` (protocolo nativo `/api/chat`) y `OpenAICompatBackend` (`/v1/chat/completions`). |
| **tool_mode** | Cómo el modelo emite llamadas a herramientas: `native` (JSON estructurado en la respuesta) o `fenced` (bloques de código tipo ` ```tool ... ``` `). Cada modelo tiene un modo por defecto en el catálogo. |
| **ModelSpec** | Dataclass con los metadatos de un modelo del catálogo: id, tag de Ollama, VRAM, contexto nativo, tool_mode, benchmarks. |
| **ModelSelection** | Resultado de `build_model_selection()`: modelo elegido + backend + num_ctx calculado + tool_mode resuelto. |
| **HardwareProfile** | Resultado del escaneo de hardware: RAM total, VRAM disponible, tipo de GPU, presupuesto de inferencia. |
| **AgentConfig** | Configuración completa que entra al harness: modelo, backend, herramientas habilitadas, seguridad, workspace, rondas máximas, etc. |
| **Skill** | Extensión de usuario en `.ci2lab/skills/<nombre>/SKILL.md`. El agente puede invocarla con la herramienta `skill` o el usuario con `/nombre` en el REPL. |
| **MCP** | Model Context Protocol — protocolo para conectar servidores de herramientas externos via stdio. Configurado en `.ci2lab/mcp.json`. Las herramientas MCP aparecen como `mcp__<servidor>__<herramienta>`. |
| **Memoria del proyecto** | Archivos `CI2LAB.md` y `AGENTS.md` en el workspace; se inyectan en el system prompt de cada sesión. |
| **Edición supervisada** | Antes de que el agente ejecute `write_file` o `edit_file`, muestra un diff y pide confirmación (a menos que `--yes` esté activo). |
| **Compactación de contexto** | Cuando el contexto se acerca al límite, se ejecuta micro-compact (elimina mensajes intermedios) + resumen LLM + trim mecánico. |
| **Motor de seguridad** | Implementación de las reglas de permisos. Los tres disponibles son `claude_experimental` (default), `ci2lab` (legado) y `opencode_experimental` (inseguro). |
| **Perfil de seguridad** | Preset de permisos: `strict`, `standard` (default), `dev`, `audit`. Se configura en `ci2lab.json`. |
| **Run log** | Artefactos JSON/JSONL generados bajo `runs/` o `--runs-dir` con cada ejecución del agente: tool_calls, mensajes, tokens, etc. |
| **Eval task** | Tarea JSON en `evals/tasks/` que define un prompt, archivos iniciales, respuestas mock y criterios de éxito/fallo para validar el harness. |
| **Benchmark task** | Tarea JSON en `benchmarks/tasks/` con un prompt real, fixtures y tests oráculo para medir la calidad del agente comparado con otros CLI. |
| **Nudge** | Mensaje de recuperación que el harness inyecta cuando el agente está atascado (loop detectado, racha de errores, formato inesperado). |
| **Peer review** | Flujo multiagente en `harness/multiagent/paper_review.py` para revisión científica con roles (autor, revisor, árbitro). |

---

## 3. Arquitectura detallada

### Flujo de datos completo

```
Usuario
  │
  ├─→ ci2lab chat / agent / ui      (ci2lab/cli/, ci2lab/ui/)
  │     │
  │     ▼
  │   cli/runtime.merge_cli_config()
  │     → Ci2LabConfig              (ci2lab/config.py)
  │     │    precedencia: defaults < ci2lab.yaml < env vars < flags CLI
  │     │
  │     ▼
  │   pipeline.prepare_session()    (ci2lab/pipeline.py)
  │     → hardware.profile()        (ci2lab/hardware/profile.py)
  │     → router.build_model_selection()  (ci2lab/router/)
  │         → catalog.load()        (ci2lab/catalog/models.json)
  │         → intent.classify()     (ci2lab/router/intent.py)
  │         → selection.score()     (ci2lab/router/selection.py)
  │     → ModelSelection            (ci2lab/contracts/types.py)
  │     │
  │     ▼
  │   pipeline.build_agent_config() → AgentConfig
  │     │
  │     ▼
  │   harness.query.run_agent()     (ci2lab/harness/query/loop.py)
  │   ┌─────────────────────────────────────────────────────┐
  │   │  REACT LOOP                                         │
  │   │  1. Preparar turno (visión/PDF si hay attachments)  │
  │   │  2. LLM call (stream o sync)  ←─ backends/          │
  │   │  3. Parsear tool calls        ←─ tools/parsing*     │
  │   │  4. Dispatch + Execute        ←─ tools/dispatch.py  │
  │   │  5. Verificar completitud     ←─ query/verifier.py  │
  │   │  6. Nudge si atascado         ←─ query/nudges.py    │
  │   │  7. Compactar contexto si     ←─ context/compact.py │
  │   │     necesario                                       │
  │   │  8. Repetir hasta respuesta   │                     │
  │   │     final o max_rounds        │                     │
  │   └─────────────────────────────────────────────────────┘
  │     │
  ▼     ▼
Respuesta final + run logs (runs/)
```

### Módulos del harness en detalle

#### `harness/backends/`

Abstracción sobre el transporte de inferencia. Implementar `LLMBackend` (en `base.py`) es todo lo que hace falta para añadir un nuevo proveedor.

- `OllamaBackend` — usa `/api/chat` con el parámetro `num_ctx` para el contexto.
- `OpenAICompatBackend` — usa `/v1/chat/completions`; sirve para vLLM, LM Studio, llama.cpp, cualquier servidor compatible.
- `factory.create_backend(selection)` — crea el backend correcto según `ModelSelection.backend`.

#### `harness/tools/`

El registro de herramientas tiene cinco partes que deben estar sincronizadas:

1. `TOOL_NAMES` — lista de nombres canónicos.
2. `DISPATCH` — mapa nombre → función ejecutora.
3. `schemas_parts/` — definición JSON Schema de cada herramienta.
4. `capabilities.py` — categorías (read, write, mutating, …).
5. Test: `tests/test_tool_registry_consistency.py` falla si hay desincronización.

Herramientas disponibles por categoría:

| Categoría | Herramientas |
|-----------|-------------|
| Lectura/exploración | `ls`, `read_file`, `read_document`, `grep`, `glob`, `file_info`, `tree`, `inspect_file` |
| Escritura/conversión | `write_file`, `edit_file`, `write_docx`, `apply_patch`, `fill_docx_template`, `docx_to_pdf`, `pdf_to_docx`, `notebook_edit` |
| Shell/git | `bash`, `git_status`, `git_diff` |
| Flujo/integraciones | `todo_write`, `ask_user`, `web_search`, `web_fetch`, `skill`, `mcp_call`, `mcp__*` |
| Visión | `analyze_image` |
| Matemáticas | `calc`, `symcalc` (pendiente de confirmar disponibilidad en todos los modos) |

#### `harness/multiagent/`

Orquestación secuencial de roles para tareas complejas:

- `orchestrator.py` — ejecuta fases con roles diferentes.
- `runner.py` — invoca subagentes.
- `roles.py` — definición de roles (researcher, reviewer, editor, …).
- `intent.py` — enrutamiento determinista basado en palabras clave.
- `paper_review.py` — flujo completo de revisión científica entre pares.
- `grounding.py` — inyección de contexto base para revisores.
- `manuscript.py` — gestión del manuscrito en revisión.
- `context_budget.py` — presupuesto de contexto por subagente.

> Las listas de palabras clave en `router/intent.py` y `harness/multiagent/intent.py` están en español porque los prompts de usuario son en español. No traducir.

#### `security/` (paquete raíz)

Implementaciones de los tres motores de seguridad más las herramientas de auditoría:

- `engine.py` — clase base y selección del motor.
- `policy.py` — definición de reglas deny/ask/allow.
- `permissions.py` — sistema de permisos por sesión.
- `decisions.py` — lógica de decisión.
- `claude_deterministic_matrix.py` — matriz de decisiones determinista para `claude_experimental`.
- `opencode_config_*.py` — capa de compatibilidad con configuración de OpenCode.
- `audit.py` — framework de auditoría no interactiva.
- `comparison.py` — comparativa entre motores.

---

## 4. Instalación paso a paso

### Prerequisitos

- Python 3.11 o 3.12 instalado.
- Ollama instalado y en el PATH.
- Al menos 4 GB de RAM libre (para los modelos más pequeños del catálogo).

### Windows PowerShell (detallado)

```powershell
# 1. Entrar en el directorio
cd C:\ruta\a\IAmultiagentica

# 2. Crear entorno virtual
py -m venv .venv

# 3. Activar entorno virtual
.\.venv\Scripts\Activate.ps1

# Si PowerShell bloquea la ejecución de scripts:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\.venv\Scripts\Activate.ps1

# 4. Instalar el paquete en modo editable con dependencias de desarrollo
pip install -e ".[dev]"

# 5. Verificar que el CLI funciona
ci2lab --help
ci2lab doctor

# 6. Instalar Ollama (si no lo tienes)
irm https://ollama.com/install.ps1 | iex
ollama --version

# 7. Iniciar Ollama si no corre en background
ollama serve

# 8. Descargar un modelo inicial
ollama pull qwen2.5-coder:7b

# 9. Primera prueba
ci2lab --model qwen2.5-coder:7b chat
```

### macOS / Linux (detallado)

```bash
# 1. Entrar en el directorio
cd /ruta/a/IAmultiagentica

# 2. Crear entorno virtual
python3 -m venv .venv

# 3. Activar
source .venv/bin/activate

# 4. Instalar
pip install -e ".[dev]"

# 5. Verificar
ci2lab doctor

# 6. Instalar Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 7. Descargar modelo
ollama pull qwen2.5-coder:7b

# 8. Primera prueba
ci2lab --model qwen2.5-coder:7b chat
```

### Usando los scripts de instalación automática

```powershell
# Windows PowerShell
.\instalar.ps1

# Windows CMD
instalar.bat

# macOS / Linux
bash instalar.sh
```

Estos scripts hacen los pasos 1–5 automáticamente. Revisa el contenido del script antes de ejecutarlo si estás en un entorno corporativo.

### Instalación de la dependencia opcional `convert`

Necesaria para `pdf_to_docx`:

```powershell
pip install -e ".[convert]"
```

---

## 5. Flujos de uso principales

### 5.1 Flujo de inicio desde cero

```
1. ci2lab doctor          → verificar entorno
2. ci2lab hardware        → detectar RAM/VRAM/GPU
3. ci2lab models recommend "tarea"  → elegir modelo
4. ollama pull <tag>      → descargar modelo
5. ci2lab --model <id> chat         → iniciar agente
```

### 5.2 Agente en modo terminal (REPL)

```powershell
ci2lab --model qwen2.5-coder:7b chat
```

- Muestra contador de tokens por turno y por conversación.
- Las sesiones se guardan en `~/.ci2lab/sessions/`.
- Para reanudar una sesión: `ci2lab --model <id> --session <ID> chat`.
- Comandos internos del REPL: `/exit`, `/quit`, `exit`, `quit`, `Ctrl+C`.
- Para invocar un skill: `/nombre-del-skill`.

### 5.3 Agente en modo una sola petición

```powershell
ci2lab --model qwen2.5-coder:7b "lista los archivos Python del proyecto"
ci2lab --model qwen2.5-coder:7b agent "resume el README"
```

Útil para scripting o integración en pipelines. El código de salida es 0 si termina bien, no-cero si hay error.

### 5.4 Interfaz web local

```powershell
ci2lab ui
ci2lab --model qwen2.5-coder:7b ui
ci2lab ui --no-open       # inicia el servidor sin abrir el navegador
ci2lab ui --port 8766     # puerto alternativo
```

La interfaz corre en `http://127.0.0.1:8765`. Funcionalidades:

- **Proyectos de conocimiento**: base de datos SQLite propia por proyecto bajo `~/.ci2lab/projects/<id>/`. Sube PDFs, notas, presentaciones; el agente recupera extractos relevantes en cada turno.
- **Carga de ficheros**: PDFs y texto se copian a `ci2lab_uploads/` y el agente los lee con `read_file` o `read_document`.
- **Contador de tokens**: por turno y por conversación, con desglose por modelo.
- **Historial de sesiones**: las sesiones quedan vinculadas al proyecto y no se pueden reanudar en otro proyecto.

> El texto de la interfaz (botones, etiquetas, menús) está en español. El agente responde en el idioma del modelo/prompt. Ver [limitaciones conocidas](KNOWN_LIMITATIONS.md).

### 5.5 Menú interactivo

```powershell
ci2lab           # abre el menú al iniciar sin subcomando
ci2lab menu      # abre el menú explícitamente
```

El menú permite elegir modelo, modo y workspace de forma guiada sin recordar flags.

### 5.6 Recomendación de modelos

```powershell
ci2lab models recommend                           # por hardware solamente
ci2lab models recommend "programa en Python"      # coding
ci2lab models recommend "razonamiento complejo"   # reasoning
ci2lab models recommend "documentos largos"       # large context
ci2lab models recommend "máquina con pocos recursos"  # edge
ci2lab models recommend --limit 3                 # limitar a 3 resultados
```

El router combina la intención detectada con el perfil de hardware para ordenar los 86 modelos del catálogo.

### 5.7 Gestión de modelos

```powershell
ci2lab models install qwen2.5-coder-7b    # muestra el plan de instalación
ci2lab models run qwen2.5-coder-7b        # abre con ollama run
ollama pull qwen2.5-coder:7b              # descarga efectiva
ollama list                                # modelos instalados en Ollama
ollama rm qwen2.5-coder:7b                # eliminar modelo del disco
```

### 5.8 Importar modelos GGUF desde Hugging Face

CI2Lab puede registrar un GGUF descargado desde Hugging Face y crear el modelo correspondiente en Ollama con `ci2lab models import-gguf`. El flujo recomendado es: buscar un repo GGUF, descargar el archivo con `hf download`, verificar la ruta local, hacer primero un `--dry-run`, revisar el Modelfile generado y solo entonces ejecutar el import real.

> `huggingface-cli` aparece como deprecated en instalaciones recientes. Usa `hf download`.

#### Flujo recomendado en PowerShell

1. Busca en Hugging Face un repositorio que publique archivos `.gguf`. En portátiles, empieza por cuantizaciones `Q4_K_M`.
2. Descarga solo el archivo que quieres usar.
3. Resuelve la ruta absoluta del `.gguf`.
4. Ejecuta `ci2lab models import-gguf --dry-run`.
5. Comprueba que el Modelfile generado contiene el `FROM` correcto y un `TEMPLATE` compatible con la familia del modelo.
6. Ejecuta el import real.
7. Verifica con `ollama list`, prueba con `ollama run` y finalmente prueba desde CI2Lab.

Ejemplo validado con GLM-4-9B chat:

```powershell
hf download bartowski/glm-4-9b-chat-GGUF `
  --include "*Q4_K_M.gguf" `
  --local-dir models/glm4-9b-chat

Get-ChildItem .\models\glm4-9b-chat

$gguf = (Resolve-Path .\models\glm4-9b-chat\glm-4-9b-chat-Q4_K_M.gguf).Path

ci2lab models import-gguf `
  --id glm4chattest `
  --repo bartowski/glm-4-9b-chat-GGUF `
  --file glm-4-9b-chat-Q4_K_M.gguf `
  --path "$gguf" `
  --family glm4 `
  --template glm4-chat `
  --ctx 16384 `
  --dry-run

ci2lab models import-gguf `
  --id glm4chattest `
  --repo bartowski/glm-4-9b-chat-GGUF `
  --file glm-4-9b-chat-Q4_K_M.gguf `
  --path "$gguf" `
  --family glm4 `
  --template glm4-chat `
  --ctx 16384

ollama list
ollama run glm4chattest

ci2lab --backend ollama --model glm4chattest --context-length 8192 --max-rounds 1 --no-stream chat
```

En el `--dry-run`, revisa especialmente estas partes:

```text
FROM C:\ruta\absoluta\al\modelo.gguf
TEMPLATE """
...
"""
PARAMETER num_ctx 16384
```

En Windows, preferir ruta absoluta evita ambigüedades. Si usas ruta relativa, escribe `.\models\...` o `./models/...`; una ruta como `models/...` puede ser interpretada por Ollama como nombre remoto.

#### Errores comunes

| Error | Causa probable | Solución |
|-------|----------------|----------|
| `huggingface-cli is deprecated` | CLI antiguo de Hugging Face | Usar `hf download ...` |
| `lookup models: no such host` | Ollama interpretó `models/...` como remoto | Usar `.\models\...`, `./models/...` o ruta absoluta |
| `400 Bad Request: invalid model name` | Nombre/tag demasiado largo o con formato no aceptado por Ollama | Usar `--id` simple, por ejemplo `glm4chattest` o `glm4chat:q4km` |
| `request exceeds available context size` | La conversación supera el contexto configurado | Subir `--context-length`, por ejemplo `8192` o `16384` |
| Funciona en `ollama run` pero falla en CI2Lab | Contexto, sesión o streaming complican el primer smoke test | Probar `--context-length 8192 --max-rounds 1 --no-stream` y una sesión limpia |

#### Buenas prácticas

- Empieza con `Q4_K_M` en portátiles.
- Evita modelos demasiado grandes para la RAM/VRAM disponible.
- Usa nombres de Ollama simples y cortos.
- Ejecuta siempre `--dry-run` antes del import real.
- En Windows, prefiere ruta absoluta para `--path`.
- Si el modelo no está en el catálogo base, conserva el `--family`, `--template`, `--ctx` y `--tool-mode` que hayas validado.

### 5.9 Backend alternativo (servidor compatible con OpenAI)

```powershell
# vLLM en localhost:8000
$env:CI2LAB_BACKEND = "openai"
$env:CI2LAB_BACKEND_URL = "http://localhost:8000/v1"
ci2lab --model nombre-del-modelo chat

# LM Studio en localhost:1234
$env:CI2LAB_BACKEND = "openai"
$env:CI2LAB_BACKEND_URL = "http://localhost:1234/v1"
ci2lab --model lm-studio-model chat

# O mediante ci2lab.yaml
```

### 5.10 Orquestación multiagente

```powershell
ci2lab --multi-agent chat
```

Activa el orquestador de subagentes secuenciales. El subsistema multiagente vive en `harness/multiagent/`; los roles, el presupuesto de contexto y el flujo de revisión entre pares están implementados y son configurables por workspace.

> **Nota:** El flag `--multi-agent` puede no estar presente en todos los checkouts del repositorio. Verificar disponibilidad con `ci2lab --help` antes de usarlo.

### 5.11 Gestión de sesiones

```powershell
ci2lab sessions                          # listar sesiones
ci2lab sessions --json                   # como JSON
ci2lab --session <ID> chat               # reanudar sesión en el REPL
```

Las sesiones se guardan en `~/.ci2lab/sessions/<ID>.json`.

Para eliminar una sesión:

```powershell
# Windows
Remove-Item "$HOME\.ci2lab\sessions\<SESSION_ID>.json"

# macOS / Linux
rm ~/.ci2lab/sessions/<SESSION_ID>.json
```

---

## 6. Comandos disponibles

### Estructura del CLI

```
ci2lab [flags globales] <subcomando> [opciones]
```

Los flags globales van siempre **antes** del subcomando.

### Flags globales más usados

| Flag | Tipo | Default | Descripción |
|------|------|---------|-------------|
| `--model` | string | — | ID del modelo (catálogo) o tag de Ollama |
| `--tool-mode` | `native`/`fenced` | del catálogo | Formato de llamadas a herramientas |
| `--workspace` / `--cwd` | ruta | directorio actual | Directorio de trabajo del agente |
| `--yes` | flag | false | Auto-confirmar herramientas peligrosas |
| `--no-stream` | flag | false | Deshabilitar streaming |
| `--no-log` | flag | false | No guardar artefactos en `runs/` |
| `--max-rounds` | int | 25 | Límite de rondas del loop |
| `--session` | string | — | ID de sesión a reanudar |
| `--runs-dir` | ruta | `runs/` | Directorio de artefactos |
| `--security-engine` | string | `claude_experimental` | Motor de seguridad |
| `--multi-agent` | flag | false | Activar orquestador multiagente |

### Subcomandos

#### `ci2lab doctor`
Verifica la instalación: paquete, Python, Ollama, dependencias. Siempre ejecutar primero si algo falla.

#### `ci2lab hardware [--json]`
Muestra RAM, VRAM, GPU, CPU y el presupuesto de inferencia calculado. Con `--json` devuelve JSON parseable.

#### `ci2lab models <acción>`
- `recommend [intención] [--limit N]` — recomendar modelos
- `install <id>` — mostrar plan de instalación
- `run <id>` — abrir con `ollama run`

#### `ci2lab chat`
REPL interactivo. Carga sesión si se pasa `--session`. Muestra tokens por turno.

#### `ci2lab agent "petición"` o `ci2lab "petición"`
Una sola petición. No carga sesión anterior (solo la guarda si `--session`).

#### `ci2lab menu`
Menú interactivo de selección de modo, modelo y workspace.

#### `ci2lab ui [--port N] [--no-open]`
Inicia el servidor web local. Por defecto abre el navegador en `http://127.0.0.1:8765`.

#### `ci2lab sessions [--json]`
Lista las sesiones guardadas.

#### `ci2lab skills`
Gestión de skills de workspace.

#### `ci2lab permissions`
Gestión y visualización del estado de permisos.

#### `ci2lab evals run [opciones]`
- Sin opciones: modo mock (no requiere Ollama).
- `--live` — con Ollama real.
- `--model <tag>` — modelo para modo live.
- `--task <id>` — una o varias tareas concretas.
- `--tasks-dir <ruta>` — directorio de tareas alternativo.

#### `ci2lab bench run [opciones]`
- `--agent ci2lab|ci2lab-multi|claude-code|codex` — agentes a comparar (se puede repetir).
- `--model <tag>` — modelo (para agentes locales).
- `--samples <n>` — muestras por tarea.
- `--task <id>` — tareas concretas.
- `--tasks-dir <ruta>` — directorio alternativo.
- `--results-dir <ruta>` — directorio de resultados.

#### `ci2lab-audit-live`
Entrypoint independiente para auditoría en vivo de modelos. Ver `ci2lab/scripts/audit_live_models.py`.

---

## 7. Configuración avanzada

### Precedencia de configuración

```
defaults del código
  < ci2lab.yaml (raíz del proyecto o ~/.ci2lab/ci2lab.yaml)
  < variables de entorno CI2LAB_*
  < flags de CLI
```

### Todas las variables de entorno

| Variable | Tipo | Descripción |
|----------|------|-------------|
| `CI2LAB_MODEL` | string | Modelo por defecto |
| `CI2LAB_BACKEND` | `ollama`/`openai` | Transporte de inferencia |
| `CI2LAB_BACKEND_URL` | URL | Endpoint compatible con OpenAI |
| `CI2LAB_OLLAMA_URL` | URL | URL base de Ollama (default: `http://localhost:11434`) |
| `CI2LAB_TOOL_MODE` | `native`/`fenced` | Modo de herramientas |
| `CI2LAB_MAX_ROUNDS` | int | Máximo de rondas del loop |
| `CI2LAB_WORKSPACE` | ruta | Directorio de trabajo |
| `CI2LAB_CWD` | ruta | Alias legado de `CI2LAB_WORKSPACE` |
| `CI2LAB_NO_LOG` | `1` | Deshabilitar logs |
| `CI2LAB_RUNS_DIR` | ruta | Directorio de artefactos de log |
| `CI2LAB_STREAM` | `true`/`false` | Activar/desactivar streaming |
| `CI2LAB_AUTO_CONFIRM` / `CI2LAB_YES` | `1` | Auto-confirmar herramientas peligrosas |
| `CI2LAB_CONFIG` | ruta | Ruta forzada al archivo de configuración |
| `CI2LAB_WRITE_TOOLS_ENABLED` | `false` | Deshabilitar `write_file` y `edit_file` |
| `CI2LAB_REQUIRE_DIFF_PREVIEW` | `true`/`false` | Forzar o saltarse el preview de diff |
| `CI2LAB_NUM_CTX` | int | Override del tamaño de contexto del modelo |

### Archivo ci2lab.yaml completo

```yaml
# Modelo e inferencia
model: qwen2.5-coder:7b
backend: ollama                         # o "openai"
backend_url: http://localhost:11434/v1  # endpoint OpenAI-compatible

# Workspace y comportamiento
workspace: .
max_rounds: 25
stream: true
auto_confirm: false

# Logging
log_runs: true
runs_dir: runs
no_log: false

# Herramientas
tool_mode: native                       # o "fenced"
write_tools_enabled: true
require_diff_preview: true

# Seguridad (ver docs/SECURITY_POLICY.md)
# security:
#   profile: standard                   # strict | standard | dev | audit
#   limits:
#     bash_timeout_seconds: 60
#     max_tool_output_chars: 10000
```

### Configurar skills de workspace

Crear el directorio y el archivo SKILL.md:

```
.ci2lab/
  skills/
    mi-skill/
      SKILL.md        ← instrucciones para el agente
```

El agente puede invocar el skill con la herramienta `skill` o el usuario puede escribir `/mi-skill` en el REPL.

### Configurar servidores MCP

Crear `.ci2lab/mcp.json` en el workspace:

```json
{
  "servers": {
    "mi-servidor": {
      "command": "python",
      "args": ["-m", "mi_servidor_mcp"],
      "env": {}
    }
  }
}
```

Las herramientas del servidor aparecen como `mcp__mi-servidor__<herramienta>`.

### Configurar hooks de workspace

Crear `.ci2lab/hooks.json`:

```json
{
  "before_tool": "echo 'Antes de la herramienta'",
  "after_tool": "echo 'Después de la herramienta'",
  "after_final_answer": "echo 'Respuesta final'"
}
```

Los hooks disponibles son `before_tool`, `after_tool`, `after_final_answer`. No hay editor de UI ni marketplace aún.

### Configurar perfiles de seguridad

En `ci2lab.json` (no `ci2lab.yaml`):

```json
{
  "security": {
    "profile": "strict",
    "limits": {
      "bash_timeout_seconds": 60,
      "max_tool_output_chars": 10000
    }
  }
}
```

### Memoria del proyecto

Crear en el workspace:

```markdown
# CI2LAB.md
Instrucciones persistentes para el agente sobre este proyecto.
```

```markdown
# AGENTS.md
Instrucciones adicionales o para subagentes.
```

Ambos archivos se inyectan automáticamente en el system prompt al iniciar una sesión en ese workspace.

---

## 8. Ejecución de tests

### Suite completa

```powershell
python -m pytest -q
```

Corre los ~905 tests. Debe estar limpia antes de cualquier merge.

### Subconjuntos útiles

```powershell
# Por archivo
python -m pytest tests/test_bash_safety.py -q

# Por nombre de test
python -m pytest -k "test_tool_registry" -q

# Con output de prints
python -m pytest tests/test_config.py -s -q

# Con detalles de fallo
python -m pytest tests/test_multiagent_orchestrator.py -v

# Solo tests que fallaron la última vez
python -m pytest --lf -q
```

### Tests clave a conocer

| Archivo | Qué valida |
|---------|------------|
| `test_tool_registry_consistency.py` | Los 5 registros de herramientas están sincronizados |
| `test_bash_safety.py` | Blocklist de bash no tiene regresiones |
| `test_bash_windows_vectors.py` | Vectores de escape específicos de Windows |
| `test_config.py` | Precedencia de configuración |
| `test_backends.py` | Backends Ollama y OpenAI-compatible |
| `test_claude_deterministic_matrix.py` | Matriz de decisiones del motor claude_experimental |
| `test_multiagent_orchestrator.py` | Orquestador multiagente |
| `test_cli_*.py` | Subcomandos del CLI |
| `test_apply_patch.py` | Herramienta apply_patch |
| `test_completion_verifier.py` | Verificador de completitud del loop |

### Notas de plataforma

- Los tests de bash con `shell=True` asumen comportamiento POSIX. En Windows algunos tests de seguridad tienen vectores específicos en `test_bash_windows_vectors.py`.
- El directorio `.pytest-tmp/` y `.pytest-tmp-single/` son directorios temporales de fixtures; no borrarlos manualmente durante un test run.
- Los tests de la carpeta `tests/redteam/` son tests de adversarios para el motor de seguridad; pueden ser lentos.

---

## 9. Ejecución de benchmarks y evaluaciones

### Evaluación del harness (`evals/`)

**Propósito:** Verificar que el harness usa las herramientas correctamente y respeta la seguridad y configuración. No es un benchmark de calidad de modelo — es verificación de comportamiento del harness.

```powershell
# Mock (sin Ollama, determinista, rápido)
ci2lab evals run
python -m ci2lab.evals.run

# Live (requiere Ollama con el modelo descargado)
ci2lab evals run --live --model llama3.1:8b
python -m ci2lab.evals.run --live --model llama3.1:8b

# Tarea concreta
ci2lab evals run --task 004_block_dangerous_bash
python -m ci2lab.evals.run --task 006_edit_file_approved

# Varias tareas
ci2lab evals run --task 001_list_files --task 002_read_file

# Directorio de tareas alternativo
ci2lab evals run --tasks-dir ./mis_tareas
```

**Tareas incluidas:**

| ID | Qué verifica |
|----|-------------|
| `001_list_files` | El agente usa `ls` para listar archivos |
| `002_read_file` | El agente usa `read_file` para leer un archivo |
| `003_find_function` | El agente usa `grep` o `glob`+`read_file` para encontrar código |
| `004_block_dangerous_bash` | `bash` con comandos peligrosos es bloqueado por la lista negra |
| `005_edit_file_denied` | Edición supervisada: si el usuario rechaza, el archivo no cambia |
| `006_edit_file_approved` | Edición supervisada: si el usuario aprueba, el archivo cambia |
| `007_write_tools_disabled` | Con `write_tools_enabled=false`, la escritura está bloqueada |

**Resultado:** Código de salida `0` si todas pasan, `1` si alguna falla. Artefactos en `evals/results/YYYY-MM-DD_HHMMSS/`.

**Interpretar resultados:**

```
evals/results/<timestamp>/
  summary.json        → totales PASS/FAIL, modo, modelo
  results.jsonl       → una línea por tarea con checks detallados
  workspaces/<id>/    → workspace usado para cada tarea
  runs/<id>/          → logs del harness (tool_calls.jsonl, etc.)
```

### Benchmarks comparativos (`benchmarks/`)

**Propósito:** Medir calidad real del agente en tareas de código frente a otros CLI agénticos. Son **live** (requieren modelos reales) y **nunca corren en CI**.

```powershell
# Solo ci2lab, agente simple
ci2lab bench run --agent ci2lab --model qwen2.5-coder:32b --samples 5

# Smoke H3: agente simple vs multiagente en tareas pequeñas
ci2lab bench run \
  --tasks-dir benchmarks/tasks/h3_smoke \
  --results-dir benchmarks/results/h3_smoke \
  --agent ci2lab --agent ci2lab-multi \
  --model qwen2.5-coder:32b --samples 1

# Matriz completa (requiere claude-code y codex configurados)
ci2lab bench run \
  --agent ci2lab --agent ci2lab-multi --agent claude-code --agent codex \
  --model qwen2.5-coder:32b --samples 5

# Tarea concreta
ci2lab bench run --agent ci2lab --task cli-01

# Desde Python
python -m ci2lab.bench.run --agent ci2lab
```

**Tareas incluidas:**

| ID | Familia | Modo de fallo que prueba |
|----|---------|--------------------------|
| `cli-01` | CLI exec | Selección de herramienta en archivos grandes (grep vs read-all) |
| `cli-02` | CLI exec | Ejecutar script y diagnosticar el paso que falla |
| `qa-01` | code Q&A | Localizar un símbolo en un repo no visto |
| `qa-02` | code Q&A | Trazar un valor entre archivos |
| `bug-01` | bug fix | Parchear un test unitario fallido (un archivo) |
| `bug-02` | bug fix | Regresión multifichero |
| `feat-01` | code gen | Implementar un stub contra una spec oculta |

**Resultado:** Artefactos en `benchmarks/results/<timestamp>/`:
- `results.jsonl` — una fila por tarea × agente × muestra.
- `summary.json` — Pass@1, Pass@k, tokens medios, coste USD imputado, latencia mediana por tarea × agente.

**Entorno de referencia:** Ver `benchmarks/ENVIRONMENT.md` para las versiones de hardware, modelo y CLI usadas en cada ejecución.

**Scripts de utilidad relacionados:**

```powershell
python scripts/run_harness_write_eval.py    # evaluación específica de write/edit
```

---

## 10. Interpretación de outputs, logs y resultados

### Logs de ejecución del agente (`runs/`)

Cada ejecución del agente (con logging activo) crea un directorio bajo `runs/` o `--runs-dir`:

```
runs/<timestamp>/
  tool_calls.jsonl    → cada llamada a herramienta con entrada, salida, tokens
  messages.jsonl      → historia de mensajes LLM
  summary.json        → resumen: duración, rondas, tokens totales, resultado
```

El formato JSONL permite analizar ejecuciones con `jq` o cualquier parser JSON.

### Tokens en el REPL y la UI

Después de cada turno en el REPL se muestran:
- Tokens de entrada de ese turno.
- Tokens de salida de ese turno.
- Tokens acumulados de la conversación (cuando Ollama los devuelve).

En la UI, el contador está siempre visible con desglose por modelo.

### Salida del agente

El agente devuelve texto en el idioma del modelo/prompt. No hay post-procesado de la respuesta final. Si el modelo usa formato Markdown, se renderiza en el terminal (con `rich`).

### Salida de `ci2lab evals run`

```
PASS  001_list_files
PASS  002_read_file
FAIL  003_find_function  → check: expected_tool_groups, expected: [["grep"]], actual: []
...
Summary: 6/7 passed (mock mode)
Exit code: 1
```

El `results.jsonl` tiene el campo `failure_reasons` con fragmentos específicos de por qué falló cada check.

### Salida de `ci2lab bench run`

`summary.json` tiene por cada par tarea × agente:
- `pass_at_1` — porcentaje de primera muestra que pasa.
- `pass_at_k` — porcentaje considerando k muestras.
- `mean_tokens` — tokens medios por muestra.
- `cost_usd` — coste imputado según `benchmarks/prices.json`.
- `median_latency_s` — latencia mediana.

### Diagnóstico de seguridad

Cuando una herramienta es bloqueada:
- Por perfil: `Error: TOOL_BLOCKED_BY_SECURITY_PROFILE: <herramienta> is disabled in <perfil> mode`
- Por blocklist de bash: `Error: command blocked by security policy (...)`
- Por política deny: el agente recibe un mensaje de rechazo y puede intentar otra vía.

---

## 11. Buenas prácticas de desarrollo

### Flujo de trabajo recomendado

1. Trabajar en ramas: nunca directamente en `main`.
2. Ejecutar las cuatro puertas antes de cada commit:
   ```powershell
   python -m ruff check ci2lab tests
   python -m ruff format ci2lab tests
   python -m mypy ci2lab
   python -m pytest -q
   ```
3. Commits pequeños y atómicos con mensaje que explica el *por qué*.
4. Añadir test antes (o junto con) el cambio de comportamiento.

### Estándares de código

- **Tipos:** anotar todas las firmas (parámetros y retorno). `mypy ci2lab` debe pasar.
- **Docstrings:** estilo Google en todos los módulos, clases y funciones públicas. Ver `harness/backends/` como referencia.
- **Módulos fachada:** los `__init__.py` con re-exportaciones están exentos de F401. Nunca dejes que `ruff --fix` los limpie. Añadir el fichero a `[tool.ruff.lint.per-file-ignores]` en `pyproject.toml`.
- **Modularidad:** mantener módulos con responsabilidad única.
- **Sin magia por tema:** el loop ReAct es task-agnostic. No añadir casos especiales en `harness/query/loop.py` para tipos concretos de tarea.

### Añadir una herramienta nueva

Actualizar los **cinco** lugares del registro (en el mismo PR):

1. `TOOL_NAMES` en `ci2lab/harness/tools/registry.py`
2. `DISPATCH` en `ci2lab/harness/tools/dispatch.py`
3. Schema JSON en `ci2lab/harness/tools/schemas_parts/`
4. Categoría en `ci2lab/harness/tools/capabilities.py`
5. Implementación en `ci2lab/harness/tools/`

El test `tests/test_tool_registry_consistency.py` verificará automáticamente la consistencia.

### Añadir un backend de inferencia nuevo

1. Crear `ci2lab/harness/backends/<nombre>.py` implementando `LLMBackend`.
2. Registrar en `ci2lab/harness/backends/factory.py`.
3. Añadir tests en `tests/test_backends.py`.
4. Actualizar `docs/STRUCTURE.md`.

Nada más cambia — el harness es independiente del backend.

### Añadir un modelo al catálogo

Editar `ci2lab/catalog/models.json`. Cada entrada necesita:

```json
{
  "id": "mi-modelo-7b",
  "name": "Mi Modelo 7B",
  "ollama_tag": "mi-modelo:7b",
  "vram_gb": 7.5,
  "context_native": 32768,
  "tool_mode": "native",
  "tier": "workstation",
  "use_cases": ["coding", "general"]
}
```

### Modificar el loop ReAct

Lee `harness/query/loop.py` entero y los comentarios antes de tocar nada. El timing de nudges/rondas es frágil: un cambio aparentemente pequeño puede romper la detección de loops o hacer que los nudges nunca lleguen.

---

## 12. Buenas prácticas de seguridad

### Reglas base que no se pueden relajar

Independientemente de la configuración:
- El agente no puede acceder a rutas fuera del workspace (`resolve_path()` lo confina).
- `--yes`/`auto_confirm` no salta la lista negra de bash ni el check de archivos secretos.
- No se pueden leer ni escribir archivos secretos por defecto (heurístico en `secret_files.py`).
- La lista negra de bash (`bash_safety.py`) es siempre activa en el perfil `standard`.

### Antes de usar `--yes` en producción

El flag `--yes` auto-confirma herramientas peligrosas (bash, write, edit). Usar solo en entornos donde estás seguro del alcance del agente. En un CI, combinar con `--workspace` explícito para acotar el alcance.

### Antes de usar `opencode_experimental`

Este motor es **inseguro** — no tiene guards duros. Solo para comparar con OpenCode en entornos de laboratorio aislados. Nunca para trabajo real.

### Auditar operaciones antes de ejecutar

```powershell
# Verificar qué haría una operación bash antes de aprobarla
python scripts/security_gate_check.py --workspace . --tool bash --target "rm archivo.txt"

# Comparar motores de seguridad
python scripts/compare_security_engines.py

# Auditoría live de modelos
ci2lab-audit-live
python scripts/audit_claude_experimental_live.py --all
```

### Política de edición supervisada

Por defecto, `write_file` y `edit_file` muestran un diff antes de ejecutar. El usuario debe aprobar cada edición. Ver [`docs/WRITE_POLICY.md`](WRITE_POLICY.md) para los detalles completos.

Para deshabilitar la escritura completamente:
```powershell
ci2lab --no-stream --yes "tarea de solo lectura"
# O en config:
# write_tools_enabled: false
```

---

## 13. Cómo añadir nuevos módulos y extensiones

### Nueva skill de workspace

Crear `.ci2lab/skills/<nombre>/SKILL.md` en el workspace donde quieras usarla. El archivo describe al agente qué hace la skill y cómo invocarla.

### Nuevo servidor MCP

Implementar un servidor MCP stdio en cualquier lenguaje y añadirlo a `.ci2lab/mcp.json`. Las herramientas se registran dinámicamente como `mcp__<servidor>__<herramienta>`.

### Nueva tarea de evaluación

1. Crear `evals/tasks/NNN_nombre.json` con la estructura de task (ver `docs/evals.md`).
2. Definir `mock_responses` para poder correr en mock sin Ollama.
3. Verificar: `python -m ci2lab.evals.run --task NNN_nombre`.

### Nueva tarea de benchmark

1. Crear `benchmarks/tasks/<familia-NN>.json` siguiendo el formato de las tareas existentes.
2. Añadir tests oráculo (verificadores ocultos al agente).
3. Documentar en `benchmarks/README.md`.

### Nueva entrada en el catálogo de modelos

Editar `ci2lab/catalog/models.json` con los campos requeridos. Verificar con `ci2lab models recommend` que aparece en las recomendaciones apropiadas.

### Nuevo motor de seguridad

Implementar en `ci2lab/security/engine.py` la interfaz del motor. Registrar en `ci2lab/security/`. Añadir documentación de validación similar a `docs/CLAUDE_EXPERIMENTAL_VALIDATION.md`.

### Nuevo subcomando CLI

1. Crear `ci2lab/cli/commands/<nombre>.py` con la función de despacho.
2. Registrar en `ci2lab/cli/main.py`.
3. Añadir tests en `tests/test_cli_*.py`.

---

## 14. Auditoría no destructiva antes de limpiar carpetas

**Antes de borrar, mover o reorganizar cualquier carpeta**, ejecutar:

```powershell
# Ver qué hay en la carpeta
Get-ChildItem <carpeta> -Recurse | Select-Object FullName, Length, LastWriteTime

# Ver si hay referencias desde el código
python -c "
import subprocess, sys
result = subprocess.run(['python', '-m', 'grep', '-r', sys.argv[1], 'ci2lab/', 'tests/', 'scripts/'], capture_output=True, text=True)
print(result.stdout or 'Sin referencias en el código.')
" <nombre-carpeta>

# Script de auditoría de seguridad
python scripts/security_gate_check.py --workspace . --tool bash --target "rm -rf <carpeta>"
```

### Carpetas que nunca deben borrarse sin revisión del equipo

| Carpeta | Por qué no borrar sin revisión |
|---------|-------------------------------|
| `audit/` | Contiene reportes de red team, análisis de seguridad y trabajo en sandbox que puede ser referencia para decisiones futuras |
| `references/` | Repositorios de referencia usados para estudiar otras implementaciones; pueden contener comparaciones o código base de decisiones de diseño |
| `runs/` | Artefactos de ejecución históricos; pueden contener trazas de sesiones de investigación |
| `evals/results/` | Resultados de evaluaciones pasadas; referencia histórica de comportamiento del harness |
| `benchmarks/results/` | Resultados de benchmarks; referencia histórica de rendimiento comparativo |
| `Examenes/` | PDFs de ejemplo / casos de uso — pueden ser datos de prueba relevantes |
| `.agents/` | Directorio de trabajo de agentes activos — puede contener estado de sesiones en progreso |

---

## 15. Partes experimentales o históricas

### Experimental (funcional pero no garantizado en todos los entornos)

- **`--multi-agent`** — El orquestador multiagente está implementado en `harness/multiagent/` pero el flag CLI puede no estar presente en todos los checkouts. Verificar con `ci2lab --help`.
- **Motor `opencode_experimental`** — Sin guards de seguridad. Solo para comparativa de laboratorio.
- **Hooks de workspace** (`.ci2lab/hooks.json`) — Implementación básica (`before_tool`, `after_tool`, `after_final_answer`). Sin editor de UI ni marketplace.
- **`analyze_image` / visión** — Funcional pero depende del soporte de visión del modelo. No todos los modelos del catálogo soportan multimodal.
- **`notebook_edit`** — Herramienta de edición de Jupyter notebooks. Pendiente de confirmar cobertura completa.
- **Peer review multiagente** (`harness/multiagent/paper_review.py`) — Flujo completo implementado para revisión científica entre pares, pero es un flujo especializado que requiere configuración específica de roles.

### Histórico / investigación (no borrar sin revisión)

- **`references/`** — Snapshots de repos de referencia (claude-code, odysseus, opencode, deepagents). Son solo lectura para el equipo; no son parte del paquete instalable.
- **`audit/redteam/`** y **`audit/redteam_sandbox/`** — Tests de adversarios ejecutados manualmente. Contienen escenarios de ataque usados para validar los motores de seguridad.
- **`docs/20260217_rudiger_user_instructions.md`** — Guía de uso y entorno de la estación de trabajo RUDIGER. Archivo histórico de referencia.
- **`Examenes/`** — PDFs de ejemplo (exámenes universitarios de matemáticas). Usados probablemente como casos de prueba para las herramientas de procesamiento de PDFs y visión. No son datos sensibles pero sí datos de prueba.
- **`inside.txt`** y **`debug.log`** — Archivos de trabajo / debug generados durante el desarrollo. Verificar contenido antes de borrar.

### Pendiente de implementar (según documentación existente)

- **Auto-pull de modelos** (`ci2lab/runtime/`) — `ensure_model_ready()` no existe; el usuario debe ejecutar `ollama pull` manualmente.
- **Rollback de git / snapshot automático** — No implementado.
- **Memoria vectorial entre sesiones** — No implementado.
- **Routing por turno entre múltiples modelos** — No implementado.
- **Editor de UI para hooks** — No implementado.
- **Benchmarks live del catálogo** — Los scores en `models.json` son estáticos.

---

## 16. Preguntas frecuentes y troubleshooting

### Instalación

**P: `ci2lab: command not found` después de instalar.**
El entorno virtual no está activado o el paquete no se instaló en él. Solución:
```powershell
.\.venv\Scripts\Activate.ps1   # Windows
pip install -e ".[dev]"
which ci2lab   # debe mostrar la ruta dentro de .venv
```

**P: `Set-ExecutionPolicy` me dice que no tengo permisos.**
Ejecutar PowerShell como administrador o usar:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**P: `pip install -e ".[dev]"` falla con error de compilación.**
Algunos paquetes (psutil, pymupdf) necesitan compiladores. En Windows: instalar [Build Tools for Visual Studio](https://visualstudio.microsoft.com/visual-cpp-build-tools/).

**P: `pdf_to_docx` no funciona.**
Requiere la dependencia opcional:
```powershell
pip install -e ".[convert]"
```

### Ollama

**P: `Connection refused` al conectar con Ollama.**
Ollama no está corriendo. Solución: `ollama serve` (o reiniciar el servicio de Ollama en Windows).

**P: `model not found` al iniciar el agente.**
El modelo no está descargado en Ollama. Ver `ollama list` y ejecutar `ollama pull <tag>`.

**P: El modelo tarda mucho en responder el primer turno.**
Ollama carga el modelo en memoria la primera vez. Normal en modelos grandes (>7B). Los turnos siguientes son más rápidos.

**P: El agente usa modo `fenced` aunque el modelo soporta `native`.**
El modelo no está en el catálogo o el ID no coincide. Solución: `ci2lab --tool-mode native --model <id> chat`.

### El agente

**P: El agente entra en un bucle sin terminar.**
El loop tiene detección de bucles y un streak de errores. Si persiste, reducir `--max-rounds` o revisar si el modelo está confundido con el formato de herramientas.

**P: `ci2lab agent --session <id>` no carga el historial anterior.**
Limitación conocida. Usar `ci2lab chat --session <id>` para reanudar con historial.

**P: El agente intenta acceder a ficheros fuera del workspace y recibe error.**
Comportamiento correcto: `resolve_path()` confina el acceso al workspace. Pasar `--workspace <ruta>` si el agente necesita acceder a otra ruta.

**P: `write_file` o `edit_file` pide confirmación aunque pasé `--yes`.**
`--yes` auto-confirma. Si sigue pidiendo confirmación, es posible que el engine de seguridad tenga una regla `ask` para esa herramienta. Revisar la configuración de permisos.

### Tests

**P: Los tests fallan con `ImportError`.**
El entorno virtual no está activado o el paquete no está instalado en él. Ver instalación.

**P: `test_tool_registry_consistency.py` falla.**
Se añadió una herramienta sin actualizar todos los registros. Ver [añadir una herramienta](#añadir-una-herramienta-nueva).

**P: Los tests de bash fallan en Windows con rutas.**
Algunos tests asumen separadores POSIX. Revisar si el test tiene un equivalente en `test_bash_windows_vectors.py`.

**P: Los tests tardan demasiado.**
Los tests de `redteam/` pueden ser lentos. Para desarrollo rápido:
```powershell
python -m pytest -q --ignore=tests/redteam
```

### Mypy

**P: `mypy ci2lab` falla en un módulo nuevo.**
Añadir tipos a todas las firmas del módulo. Si el módulo no es estrictamente necesario en mypy strict, añadirlo a `[[tool.mypy.overrides]]` en `pyproject.toml` solo con `ignore_missing_imports = true` inicialmente, pero la meta es añadirlo al grupo strict.

**P: Mypy se queja de imports en `__init__.py`.**
Los `__init__.py` que re-exportan internos tienen `F401` ignorado en ruff, pero mypy puede necesitar `# noqa: F401` o una entrada explícita en `__all__`. Ver otros `__init__.py` del paquete como referencia.

### Ruff

**P: `ruff --fix` elimina imports necesarios en `__init__.py`.**
Añadir el fichero a `[tool.ruff.lint.per-file-ignores]` en `pyproject.toml` con `["F401"]`. Nunca dejar que ruff elimine re-exportaciones intencionadas.

### Web UI

**P: La interfaz web está en español pero quiero que esté en inglés.**
Limitación conocida del proyecto. El frontend (`ci2lab/ui/static/`) está en español. Ver [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md). Contribución bienvenida.

**P: La web UI no se abre automáticamente en el navegador.**
Usar `ci2lab ui --no-open` para que solo inicie el servidor, o abrir manualmente `http://127.0.0.1:8765`.

**P: El puerto 8765 ya está en uso.**
```powershell
ci2lab ui --port 8766
```

### CI/CD

**P: CI falla en `ruff format --check`.**
El código no está formateado. Ejecutar localmente `python -m ruff format ci2lab tests` y hacer commit.

**P: CI falla en mypy pero localmente pasa.**
Verificar que la versión de mypy es la misma (ver `pyproject.toml`). CI corre en Python 3.11 y 3.12; verificar que no hay incompatibilidades de tipos entre versiones.

---

*Última actualización: 2026-06-30. Para cambios recientes, ver [`CHANGELOG.md`](../CHANGELOG.md).*
