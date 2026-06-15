# Auditoría del flujo actual del arnés Ci2Lab

**Fecha:** 2026-06-09  
**Alcance:** arnés agéntico MVP en `IAmultiagentica` / paquete `ci2lab`  
**Método:** inspección estática del código, ejecución de `python -m ci2lab.cli --help`, `python -m ci2lab --help`, y suite de tests.

**Actualización (fase saneamiento 2026-06-09):** ver [§16](#16-actualización--fase-de-saneamiento) y [`write_edit_tools_status.md`](write_edit_tools_status.md).

**Cierre de hito (2026-06-09):** harness validado mock + live — ver [§18](#18-cierre-de-hito--validación-mocklive) y [`live_eval_status.md`](live_eval_status.md). Las secciones §3–§15 son snapshot histórico de la primera auditoría; §16–§18 reflejan el estado actual.

**Actualización (2026-06-12):** refactor estructural — CLI en `ci2lab/cli/`, bucle en `harness/query/loop.py`, `pipeline.build_agent_config()`, consola en `ci2lab/console.py`, MCP/skills/UI integrados. Ver [`STRUCTURE.md`](../STRUCTURE.md). Las secciones §3–§15 siguen siendo snapshot histórico salvo rutas de archivo obsoletas (`cli.py`, `harness/loop.py`).

**Actualización (2026-06-10):** `hardware/` y `router/` implementados en CLI. Ver [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).

---

## 1. Resumen ejecutivo

El proyecto tiene un **arnés agéntico ReAct funcional** integrado en el paquete `ci2lab`. El usuario invoca la CLI (`ci2lab` o `python -m ci2lab.cli`), que resuelve config en `cli/runtime.py`, prepara sesión vía `pipeline.prepare_session`, construye `AgentConfig` con `pipeline.build_agent_config`, y delega en `harness.query.loop.run_agent`. El bucle llama a Ollama por HTTP (API OpenAI-compatible), parsea tool calls (nativas, XML o fenced), ejecuta herramientas, y devuelve resultados al modelo hasta respuesta final o `max_rounds`.

**Estado general:**

| Área | Estado |
|------|--------|
| CLI + entrypoints | ✅ Funcional (`python -m ci2lab`, `python -m ci2lab.cli`) |
| Bucle ReAct | ✅ Completo (streaming, anti-bucle, sesiones) |
| Cliente LLM (Ollama/httpx) | ✅ Errores accionables + exit codes |
| Tools de lectura (`ls`, `read_file`, `grep`, `glob`) | ✅ Implementadas |
| `bash` con confirmación + blocklist | ✅ Confirmación + blocklist (incluso con `--yes`) |
| `write_file` / `edit_file` | ✅ Habilitadas en modo supervisado — ver `WRITE_POLICY.md` y `write_edit_tools_status.md` |
| `contracts/types.py` | ⚠️ **Ya integrado** en el flujo real (`ModelSelection` es el contrato activo) |
| `hardware/`, `router/`, `runtime/` | 🔲 Solo esqueleto (`__init__.py` con docstring) |
| Router multi-modelo | 🔲 No implementado; fallback a `default_selection` |
| Config centralizada (`config.py`, `ci2lab.yaml`) | ✅ Implementada |
| `--workspace` | ✅ Alias de `--cwd` |
| Tests automatizados | ✅ Suite ampliada (config, bash safety, llm errors, parsing) |

**Modelo por defecto (sin cambios en saneamiento):** `llama3.1:8b` vía `config.DEFAULT_MODEL`, `pipeline.py` o `CI2LAB_MODEL`. Override con `--model` o `ci2lab.yaml`.

**Discrepancia estructural:** no existen `ls.py` ni `read_file.py` separados; las tools de filesystem viven en `harness/tools/filesystem.py`.

---

## 2. Estado actual del repo

### 2.1 Árbol de archivos relevantes

```text
IAmultiagentica/
├── pyproject.toml              # paquete, deps, entrypoint ci2lab, force-include prompts
├── README.md
├── ci2lab/
│   ├── __init__.py             # __version__
│   ├── __main__.py             # delega en cli.main()
│   ├── cli.py                  # argparse, subcomandos, orquestación
│   ├── pipeline.py             # prepare_session (router stub → default_selection)
│   ├── contracts/
│   │   ├── types.py            # ModelSelection, HardwareProfile, etc. — EN USO
│   │   └── README.md
│   ├── hardware/__init__.py    # esqueleto
│   ├── router/__init__.py      # esqueleto
│   ├── runtime/__init__.py     # esqueleto
│   └── harness/
│       ├── __init__.py         # exports + default_selection()
│       ├── loop.py             # bucle ReAct principal
│       ├── llm_client.py       # HTTP → Ollama
│       ├── parsing.py          # native / XML / fenced
│       ├── messages.py         # historial assistant/tool
│       ├── prompts.py          # ensambla system prompt
│       ├── prompts/
│       │   ├── system.md
│       │   └── fenced_tools.md
│       ├── permissions.py      # confirmación bash/write/edit
│       ├── context.py          # trim historial
│       ├── session.py          # ~/.ci2lab/sessions/
│       ├── repl.py             # modo chat interactivo
│       ├── types.py            # AgentConfig, ToolCall, ToolResult
│       └── tools/
│           ├── registry.py     # schemas + dispatch + execute_tool
│           ├── bash.py
│           ├── filesystem.py   # ls, read_file, grep, glob, write_file, edit_file
│           └── paths.py        # resolve_path (sandbox)
├── docs/
│   ├── STRUCTURE.md
│   ├── HARDWARE_ROUTER_HANDOFF.md
│   └── audits/
│       └── current_harness_flow_audit.md   # este informe
├── references/                 # notas de extracción (no código producto)
└── tests/                      # 12 tests del harness
```

### 2.2 Qué tiene lógica vs. esqueleto

| Ruta | Lógica | Notas |
|------|--------|-------|
| `ci2lab/cli.py` | ✅ | CLI completa: turno único, REPL, sessions, doctor |
| `ci2lab/pipeline.py` | ✅ (parcial) | Intenta importar router; fallback si `ImportError` |
| `ci2lab/contracts/types.py` | ✅ | Tipos compartidos; `ModelSelection` consumido por arnés |
| `ci2lab/harness/**` | ✅ | Arnés completo |
| `ci2lab/hardware/` | 🔲 | Solo `__init__.py` |
| `ci2lab/router/` | 🔲 | Solo `__init__.py` |
| `ci2lab/runtime/` | 🔲 | Solo `__init__.py` |
| `ci2lab/config/` | ❌ | No existe (mencionado en STRUCTURE.md) |
| `ci2lab/catalog/` | ❌ | No existe (mencionado en STRUCTURE.md) |

---

## 3. Flujo completo de ejecución

Ejemplo: `python -m ci2lab.cli "lista los archivos"`

### Paso a paso

1. **Invocación del módulo**  
   `python -m ci2lab.cli` ejecuta `ci2lab/cli.py` como `__main__` → llama `main()` → `sys.exit(main())`.

   Alternativa equivalente: `python -m ci2lab` → `ci2lab/__main__.py` → `ci2lab.cli.main()`.

2. **Parseo de argumentos** (`cli.main`)  
   - `prompt` posicional = `"lista los archivos"`.  
   - Sin subcomando → rama directa en línea 65–66.  
   - Flags por defecto: `--tool-mode native`, `--cwd` = `os.getcwd()` absoluto, `--max-rounds 25`, `--yes` false, streaming activo.  
   - `--model` = `None` (se resuelve después).

3. **Preparación de sesión** (`_resolve_selection` → `pipeline.prepare_session`)  
   - Intenta `from ci2lab.hardware.profiler import scan_hardware` etc. → **falla con `ImportError`**.  
   - Fallback: `tag = force_model or os.environ.get("CI2LAB_MODEL", "llama3.1:8b")`.  
   - Devuelve `(None, default_selection(tag, tool_mode))` → `ModelSelection` con `backend_url=http://localhost:11434/v1`, `supports_tools=True`.

4. **Config del agente** (`_build_config`)  
   - `AgentConfig(cwd, max_rounds, auto_confirm=args.yes, stream=not args.no_stream, session_id)`.

5. **Ejecución del turno** (`_run_turn` → `harness.run_agent`)  
   - Imprime modelo y CWD con Rich.  
   - Entra al bucle ReAct.

6. **Inicialización del bucle** (`loop.run_agent`)  
   - `LLMClient(selection)` → URL `http://localhost:11434/v1/chat/completions`.  
   - `build_system_prompt(selection, cwd)` → lee `system.md` + bloque entorno + (opcional) `fenced_tools.md`.  
   - Historial inicial: `[system, user]`.  
   - `tools = FUNCTION_SCHEMAS` si `selection.supports_tools`.

7. **Por cada ronda** (hasta `max_rounds`):  
   a. `trim_messages(history, selection.context_length)` — recorta historial antiguo.  
   b. `_call_llm(client, trimmed, tools, stream)` — streaming con Rich `Live` o `client.chat`.  
   c. `resolve_tool_calls(content, llm_response.tool_calls, tool_mode, skip_fenced_if_native=True en native)`.  
   d. **Si no hay calls:** respuesta final → `append_assistant_turn` → guardar sesión → `break`.  
   e. **Si hay calls:** detección de bucle (misma firma 2 veces) → mensaje de desbloqueo o ejecución:  
      - `append_assistant_turn(history, content, calls)`  
      - Por cada call: `execute_tool(call, cfg)` en `registry.py`  
      - `append_tool_results(history, results)`  
      - Guardar sesión si `session_id` definido.

8. **Ejecución de tool `ls`** (caso típico para "lista los archivos"):  
   - `check_permission("ls", …)` → allow directo (no está en `CONFIRM_TOOLS`).  
   - `_DISPATCH["ls"]` → `filesystem.ls(cfg.cwd, path=".")`  
   - `resolve_path` confina rutas al `cwd`.  
   - Resultado truncado a `max_tool_output_chars` (10 000).  
   - Mensaje `role: tool` con `tool_call_id` añadido al historial.

9. **Siguiente ronda**  
   El modelo recibe historial con assistant+tool_calls y resultados; genera respuesta final en texto.

10. **Salida al usuario**  
    - Streaming: tokens en vivo; al final newline si hay texto.  
    - Sin streaming: imprime `final_text`.  
    - `run_agent` devuelve `str`; CLI retorna exit code `0`.

---

## 4. Diagrama textual del flujo

```text
Usuario: python -m ci2lab.cli "lista los archivos"
  ↓
ci2lab/cli.py::__main__  →  main(argv)
  ↓
argparse: prompt="lista los archivos", cwd=abs(getcwd()), tool_mode=native, ...
  ↓
_resolve_selection(args, prompt)
  ↓
ci2lab/pipeline.py::prepare_session()
  ├─ try: hardware.profiler + router.resolve + runtime.ensure  → ImportError
  └─ except: default_selection(CI2LAB_MODEL | "llama3.1:8b")
  ↓
_build_config(args)  →  AgentConfig
  ↓
_run_turn(prompt, args)
  ↓
ci2lab/harness/loop.py::run_agent(user_prompt, selection, config)
  ├─ LLMClient(selection)
  ├─ build_system_prompt()  ← harness/prompts.py + prompts/*.md
  ├─ history = [system, user]
  └─ FOR round in 1..max_rounds:
       ├─ trim_messages(history, context_length)
       ├─ _call_llm()
       │    ├─ stream: LLMClient.stream_chat() → StreamToken* → LLMResponse
       │    └─ no-stream: LLMClient.chat()
       ├─ resolve_tool_calls()  ← harness/parsing.py
       │    ├─ native_to_tool_calls (prioridad)
       │    ├─ parse_xml_blocks
       │    └─ parse_fenced_blocks (si no native-only skip)
       ├─ si sin calls → respuesta final → break
       └─ si hay calls:
            ├─ execute_tool()  ← harness/tools/registry.py
            │    ├─ check_permission()  ← harness/permissions.py
            │    └─ _DISPATCH[name](config, args)
            │         ├─ bash → tools/bash.py::run_bash
            │         └─ ls/read/grep/glob/write/edit → tools/filesystem.py
            └─ append_tool_results()  ← harness/messages.py
  ↓
respuesta final (str) + exit 0
```

**Flujos alternativos de CLI:**

```text
ci2lab chat        → cli._run_repl → harness/repl.py::run_repl → run_agent por línea
ci2lab agent "…"   → _run_turn (mismos flags en subparser)
ci2lab sessions    → harness/session.py::list_sessions
ci2lab doctor      → httpx GET {CI2LAB_OLLAMA_URL}/api/tags
```

---

## 5. Funciones importantes

| Archivo | Función/clase | Responsabilidad | Quién la llama | Qué devuelve | Riesgos/observaciones |
|---------|---------------|-----------------|----------------|--------------|----------------------|
| `cli.py` | `main()` | Entry CLI, routing subcomandos | `__main__.py`, entrypoint `ci2lab` | `int` exit code | `--cwd` existe; no hay `--workspace` |
| `cli.py` | `_run_turn()` | Un turno de agente | `main()` | exit code | Captura solo `KeyboardInterrupt` |
| `cli.py` | `_resolve_selection()` | Obtiene `ModelSelection` | `_run_turn`, `_run_repl` | `ModelSelection` | Siempre fallback sin router |
| `cli.py` | `_cmd_doctor()` | Health check paquete + Ollama | `main()` | 0/1 | URL base sin `/v1` (correcto para `/api/tags`) |
| `pipeline.py` | `prepare_session()` | Integración router↔arnés | CLI | `(HardwareProfile\|None, ModelSelection)` | `pull` ignorado en fallback |
| `harness/__init__.py` | `default_selection()` | ModelSelection de prueba | `pipeline` fallback | `ModelSelection` | Default `llama3.1:8b` |
| `harness/loop.py` | `run_agent()` | Bucle ReAct completo | CLI, REPL | `str` final | Error LLM → mensaje genérico, no re-lanza |
| `harness/loop.py` | `_call_llm()` | Streaming o chat síncrono | `run_agent` | `LLMResponse` | Si stream sin LLMResponse final, usa buffer |
| `harness/llm_client.py` | `LLMClient` | HTTP OpenAI-compatible | `run_agent` | — | Nuevo `httpx.Client` por llamada |
| `harness/llm_client.py` | `chat()` / `stream_chat()` | POST chat/completions | `_call_llm` | `LLMResponse` / iterator | `raise_for_status()` sin mensaje amigable |
| `harness/parsing.py` | `resolve_tool_calls()` | Orquesta parsers | `run_agent` | `list[ToolCall]` | En native, fenced ignorado si `tool_calls=[]` |
| `harness/parsing.py` | `native_to_tool_calls()` | Normaliza API nativa | `resolve_tool_calls` | `list[ToolCall]` | Filtra nombres no en `TOOL_NAMES` |
| `harness/messages.py` | `append_assistant_turn()` | Añade assistant (+ tool_calls) | `run_agent` | `None` | Serializa args como JSON string |
| `harness/messages.py` | `append_tool_results()` | Añade mensajes `role: tool` | `run_agent` | `None` | `tool_call_id` requerido por API |
| `harness/prompts.py` | `build_system_prompt()` | System prompt dinámico | `run_agent` | `str` | Lee `.md` del filesystem |
| `harness/context.py` | `trim_messages()` | Recorte por tokens estimados | `run_agent` | `list[dict]` | Estimación ~4 chars/token, grosera |
| `harness/permissions.py` | `check_permission()` | Gate confirmación | `execute_tool` | `(bool, str\|None)` | Solo bash/write/edit |
| `harness/tools/registry.py` | `execute_tool()` | Despacho + permisos + truncado | `run_agent` | `ToolResult` | `Exception` → string al modelo |
| `harness/tools/registry.py` | `FUNCTION_SCHEMAS` | Schemas OpenAI tools | `run_agent` → LLM | `list[dict]` | Incluye write/edit aunque roadmap diga futuro |
| `harness/tools/paths.py` | `resolve_path()` | Sandbox de rutas | filesystem tools | `Path` | `PathViolationError` no tipificada en registry |
| `harness/tools/bash.py` | `run_bash()` | subprocess shell | `execute_tool` | `str` | `shell=True`, sin blocklist |
| `harness/tools/filesystem.py` | `ls`, `read_file`, etc. | I/O confinada | `execute_tool` | `str` | `grep` usa `rg` si existe |
| `harness/session.py` | `save_session()` | Persistencia JSON | `run_agent`, REPL | `Path` | Solo si `session_id` set |
| `harness/repl.py` | `run_repl()` | Loop interactivo | CLI `chat` | `None` | Auto-asigna `session_id` |
| `contracts/types.py` | `ModelSelection` | Contrato router→arnés | Todo el harness | dataclass | **Integrado activamente** |

---

## 6. Tools actuales

| Tool | Archivo | Parámetros | Permiso requerido | Qué hace | Riesgos |
|------|---------|------------|-------------------|----------|---------|
| `bash` | `tools/bash.py` | `command` (string) | **Confirmación** (`CONFIRM_TOOLS`) o `--yes` | `subprocess.run(command, shell=True, cwd=cwd, timeout=60s)` | Ejecución arbitraria de shell; sin blocklist (`rm -rf`, `curl \| sh`, etc.) |
| `read_file` | `tools/filesystem.py` | `path`, `offset?`, `limit?` | Allow | Lee archivo UTF-8, líneas numeradas, max ~2000 líneas | Path sandbox vía `resolve_path`; archivos binarios como texto |
| `ls` | `tools/filesystem.py` | `path?` (default `.`) | Allow | Lista dir (oculta dotfiles) | Solo dentro de `cwd` |
| `grep` | `tools/filesystem.py` | `pattern`, `path?`, `glob?`, `ignore_case?`, `max_results?` | Allow | `rg` si disponible; fallback Python `rglob` | Fallback puede ser lento en repos grandes; no respeta `.gitignore` en fallback |
| `glob` | `tools/filesystem.py` | `pattern`, `path?` | Allow | `Path.glob`, max 100 resultados | Patrones amplios pueden ser costosos |
| `write_file` | `tools/filesystem.py` | `path`, `content` | **Confirmación** | Crea dirs y sobrescribe archivo | Ya operativo; puede destruir archivos tras confirmar |
| `edit_file` | `tools/filesystem.py` | `path`, `old_string`, `new_string`, `replace_all?` | **Confirmación** | Reemplazo exacto de texto | Ya operativo; reemplazo parcial puede fallar si `old_string` ambiguo |

**Registro central:** schemas y dispatch en `harness/tools/registry.py`.  
**Nombres alias en parsing:** `shell`→`bash`, `read`→`read_file`, `write`→`write_file`, `edit`→`edit_file`.

---

## 7. Flujo de permisos

### Dónde se decide la confirmación

1. `registry.execute_tool()` llama `check_permission(name, permission_summary(name, args), auto_confirm=config.auto_confirm, confirm_callback=config.confirm_callback)`.
2. `permissions.CONFIRM_TOOLS = {"bash", "write_file", "edit_file"}`.
3. Si la tool **no** está en el set → `(True, None)` inmediato.
4. Si `auto_confirm=True` (flag CLI `--yes`) → allow sin preguntar.
5. Si no → `default_confirm()` hace `input("[s/N]")`; respuestas válidas: `s`, `si`, `sí`, `y`, `yes`.
6. Si denegado → `ToolResult` con error devuelto al modelo (no excepción).

### Cómo funciona `--yes`

- CLI: `--yes` → `AgentConfig.auto_confirm=True`.
- Afecta solo tools en `CONFIRM_TOOLS`.
- **No** desactiva sandbox de rutas ni limita comandos bash.

### ¿Puede ejecutarse `bash` sin permiso accidentalmente?

| Escenario | ¿Se ejecuta bash? |
|-----------|-------------------|
| Usuario responde `n`/Enter en prompt | No — error al modelo |
| Usuario usa `--yes` | Sí — intencional |
| Tool no es `bash` | N/A |
| Modelo llama `bash` vía fenced en modo `native` con `tool_calls=[]` | **No** — fenced ignorado (ver §10) |
| `read_file`/`ls`/`grep`/`glob` | Sí — sin confirmación (solo lectura) |

**Riesgo residual:** `write_file`/`edit_file` requieren confirmación, pero **ya están implementados**. Un modelo puede solicitar escritura; si el usuario confirma (`s` o `--yes`), se modifica el disco.

### Comandos peligrosos no bloqueados

No hay blocklist ni allowlist en `bash.py`. Cualquier comando aprobado se ejecuta con privilegios del usuario en `cwd`, incluyendo:

- Destrucción de datos (`rm`, `del`, reformateo)
- Exfiltración (`curl`, `scp`, lectura de `~/.ssh`)
- Modificación de git history, instalación de paquetes, fork bombs, etc.

La única mitigación actual es la **confirmación interactiva** para `bash` (y write/edit).

---

## 8. Flujo de prompts

### Dónde está el system prompt

- Plantilla base: `ci2lab/harness/prompts/system.md`
- Ensamblado: `ci2lab/harness/prompts.py::build_system_prompt()`

### Cómo se cargan snippets de tools

- `_read("system.md")` siempre.
- Bloque dinámico `## Entorno` (cwd, fecha, modelo, SO).
- `fenced_tools.md` **solo si** `tool_mode == "fenced"` **o** `not selection.supports_tools`.
- En modo `native` con `supports_tools=True` (caso por defecto): **no** se incluye `fenced_tools.md`.

### Qué se manda al modelo

Por ronda, en el POST a Ollama:

```json
{
  "model": "<ollama_tag>",
  "messages": [ /* system, user, assistant, tool, ... */ ],
  "temperature": 0.2,
  "max_tokens": 4096,
  "stream": true|false,
  "tools": [ /* FUNCTION_SCHEMAS — solo si native + supports_tools */ ]
}
```

El system prompt describe las 7 herramientas en tabla Markdown y reglas de uso, pero **no** incluye ejemplos fenced en modo native.

### Alineación prompt ↔ tools

| Aspecto | Estado |
|---------|--------|
| Herramientas listadas en `system.md` | Coincide con `TOOL_NAMES` / schemas |
| Instrucción de usar tools antes de responder | Presente |
| Formato fenced documentado al modelo | Solo en modo fenced |
| Function calling nativo | Schemas enviados por API; prompt no explica formato JSON de tools |

### Qué puede impedir uso correcto de tools

1. **Modelo sin soporte fiable de function calling** en Ollama → respuestas solo texto, sin `tool_calls`.
2. **Modo native + `tool_calls=[]`**: fenced en el contenido **no se parsean** (ver §10) → el agente puede “decir” que listó archivos sin ejecutar `ls`.
3. **Modelo por defecto `llama3.1:8b`** puede comportarse distinto a `qwen2.5-coder:7b` en tool use.
4. **Prompt en español**, schemas en inglés — suele funcionar, pero modelos pequeños pueden ignorar tools.
5. **Sin mensaje explícito** en system prompt de “debes usar function calling, no simules resultados”.
6. **Anti-bucle** puede inyectar “deja de repetir herramienta” y forzar respuesta sin evidencia real.

---

## 9. Cliente LLM y comunicación con Ollama

### Cómo se llama a Ollama

- Clase `LLMClient` en `harness/llm_client.py`.
- URL: `{selection.backend_url}/chat/completions` → default `http://localhost:11434/v1/chat/completions`.
- Cliente: `httpx` síncrono, timeout 300 s.

### Payload

Ver §8. Tools en payload solo cuando:

```python
tools and selection.supports_tools and selection.tool_mode == "native"
```

### Parseo de respuesta

- No-stream: `data["choices"][0]` → `message.content` + `message.tool_calls`.
- Stream: SSE `data: {...}`; acumula `delta.content` y `delta.tool_calls` por índice; emite `StreamToken` y finalmente `LLMResponse`.

### Gestión de errores

| Error | Comportamiento actual |
|-------|----------------------|
| Conexión rechazada (Ollama apagado) | `httpx` exception → capturada en `run_agent` → `"Error al contactar el modelo: …"` impreso en rojo; retorna ese string |
| HTTP 4xx/5xx | `raise_for_status()` → misma captura genérica |
| JSON inválido en stream | Chunk ignorado (`continue`) |
| Modelo inexistente | Error HTTP de Ollama (típicamente 404/500) → mensaje genérico |
| Timeout | Exception httpx → mensaje genérico |

**No hay:** retry, diagnóstico “¿Ollama está corriendo?”, sugerencia `ollama serve`, ni distinción modelo-not-found vs connection-refused en el bucle (solo `doctor` lo comprueba aparte).

### Variables de entorno

| Variable | Uso |
|----------|-----|
| `CI2LAB_MODEL` | Tag Ollama por defecto en fallback |
| `CI2LAB_OLLAMA_URL` | Solo en `doctor` (base `http://localhost:11434`, sin `/v1`) |

`ModelSelection.backend_url` no se sobreescribe desde env en el fallback actual.

---

## 10. Parsing de tool calls

### Orden de resolución (`resolve_tool_calls`)

1. **Nativas:** si `native_calls` truthy → `native_to_tool_calls()`; si produce calls, return.
2. **XML:** `parse_xml_blocks()` — `<tool_call>`, `<invoke name="…"><parameter>`, DSML normalizado.
3. **Skip fenced:** si `tool_mode=="native"` y `native_calls is not None` → return `[]`.
4. **Fenced:** `parse_fenced_blocks()` — `` ```tool_name\n...\n``` ``.

### Formatos soportados

| Formato | Función | Ejemplo |
|---------|---------|---------|
| OpenAI/Ollama native | `native_to_tool_calls` | `tool_calls[].function.name/arguments` |
| Fenced | `parse_fenced_blocks` | `` ```ls\n.\n``` `` |
| XML invoke | `parse_xml_blocks` | `<invoke name="bash">…` |
| DSML (DeepSeek) | `_normalize_dsml` + XML | Variantes con pipes unicode |

### Limitaciones importantes

1. **Native mode fenced suppression:** `llm_response.tool_calls` siempre es `list` (nunca `None`). En native, si el modelo devuelve `[]` pero escribe fences en `content`, **no se ejecutan tools** (paso 3 devuelve `[]`).
2. **Nombres desconocidos** en native se descartan silenciosamente.
3. **`parse_arguments` fallback:** JSON inválido en native → `{"command": raw}` (sesgo a bash).
4. **`strip_tool_markup`:** limpia fences/XML del texto mostrado al usuario.
5. **Schemas incluyen write/edit** pero el roadmap de producto los trata como futuros — el parsing ya los soporta.

---

## 11. Empaquetado y ejecución CLI

### `python -m ci2lab.cli`

✅ Verificado: muestra help de argparse.

### `python -m ci2lab`

✅ Verificado: `__main__.py` → `cli.main()`, mismo help.

### Entrypoint `ci2lab`

Declarado en `pyproject.toml`:

```toml
[project.scripts]
ci2lab = "ci2lab.cli:main"
```

✅ Correcto. En el entorno de auditoría el paquete **no estaba instalado** (`pip show ci2lab` → not found); tras `pip install -e .` el comando `ci2lab` estaría disponible.

### Prompts `.md` en el paquete

```toml
[tool.hatch.build.targets.wheel.force-include]
"ci2lab/harness/prompts" = "ci2lab/harness/prompts"
```

✅ Incluye el directorio en el wheel. En desarrollo editable, `prompts.py` resuelve vía `Path(__file__).parent / "prompts"` — funciona.

### Dependencias runtime

`httpx`, `psutil`, `rich` (psutil aún no usado por el arnés; reservado para hardware profiler futuro).

---

## 12. Qué está ya hecho

- **Migración del MVP** del arnés al repo producto `IAmultiagentica`.
- **CLI funcional** con atajo posicional, subcomandos `agent`, `chat`, `sessions`, `doctor`.
- **Harness ReAct** completo: multi-ronda, streaming Rich, anti-bucle, trim de contexto.
- **Tools:** `bash`, `read_file`, `ls`, `grep`, `glob`, `write_file`, `edit_file` (las dos últimas ya en código).
- **Confirmación** para `bash`, `write_file`, `edit_file`; flag `--yes`.
- **Cliente Ollama** vía httpx (API OpenAI-compatible).
- **Parsing** multi-formato (native, XML, fenced).
- **Sandbox de rutas** (`resolve_path`) para tools de filesystem.
- **Sesiones** persistentes en `~/.ci2lab/sessions/` (REPL + `--session`).
- **Contrato `ModelSelection`** integrado entre pipeline y arnés.
- **README** y docs de estructura/handoff.
- **Tests:** 12 tests automatizados cubriendo loop, parsing, tools, context, session.

---

## 13. Qué falta por hacer

### Prioridad alta

| Item | Estado actual |
|------|---------------|
| `config.py` | No existe; toda config vía CLI flags + env sueltos |
| `ci2lab.yaml` | No existe |
| `--workspace` | No existe; equivalente parcial: `--cwd` |
| Validación de rutas | Parcial (`resolve_path`); `PathViolationError` no documentada al usuario |
| Errores claros si Ollama falla | Genéricos en bucle; solo `doctor` da diagnóstico |
| Alinear modelo por defecto | Código: `llama3.1:8b`; operación deseada: `qwen2.5-coder:7b` |

### Prioridad media

| Item | Estado actual |
|------|---------------|
| `run_logger.py` | No existe; solo prints Rich |
| `grep` / `glob` | **Ya implementados** en `filesystem.py`; falta madurar (tests dedicados, .gitignore en fallback) |
| Tests manuales/automáticos | 12 unit tests; sin integración con Ollama real |

### Prioridad futura

| Item | Estado actual |
|------|---------------|
| ~~`write_file` / `edit_file`~~ | **Superado** — modo supervisado con diff preview; ver [`WRITE_POLICY.md`](../WRITE_POLICY.md) |
| ~~Diff preview~~ | **Superado** — `write_preview.py`, evals `005`–`007` |
| Git snapshot / rollback | No existe |

### Fuera de alcance ahora

- Routing multi-modelo (`hardware/`, `router/`, `runtime/` reales)
- Hardware profiler
- Wrappers externos / MCP / UI
- Catálogo `models.json` (carpeta `catalog/` no creada)

---

## 14. Riesgos actuales

### Seguridad

- **`bash` con `shell=True`** y sin blocklist: riesgo alto si el usuario confirma o usa `--yes`.
- **`write_file`/`edit_file` operativos** pese a roadmap “futuro”: riesgo de modificación de disco tras confirmación.
- **Confirmación por stdin** vulnerable en pipelines no interactivos (EOF → deny, comportamiento correcto).

### Rutas

- Sandbox por `resolve_path` es sólido para path traversal directo.
- **Symlinks** fuera del workspace: no hay comprobación explícita post-`resolve()`; un symlink dentro de `cwd` podría apuntar fuera.
- **`PathViolationError`** se convierte en `"Error: …"` genérico vía `execute_tool` broad except.

### Permisos

- Solo 3 tools gated; lectura libre incluye cualquier archivo bajo `cwd`.
- `--yes` anula toda confirmación de escritura y shell.

### Errores sin manejar / UX

- Fallo Ollama en mitad de tarea: mensaje rojo, sin hint de `ci2lab doctor` o `ollama serve`.
- Modelo que no soporta tools: puede alucinar resultados (especialmente con fenced suprimido en native).
- Streaming + tool_calls vacíos: difícil de depurar sin logs estructurados.

### Dependencia del cwd

- Default `os.getcwd()` — ejecutar desde directorio incorrecto cambia el sandbox.
- Sesiones guardan `cwd` pero no hay validación al reanudar.

### Imports y empaquetado

- `pipeline` importa módulos futuros dentro de `try/except ImportError` — seguro.
- `docs/STRUCTURE.md` referencia `catalog/` y `config/` inexistentes — confusión para nuevos devs.

### Experiencia si Ollama no está corriendo

- Turno único: `"Error al contactar el modelo: [ConnectError…]"` y exit 0 (no exit de error).
- `doctor` sí devuelve exit 1.

---

## 15. Próximos pasos recomendados

Orden sugerido para quien continúe el desarrollo (sin implementar en esta auditoría):

1. **Config centralizada** (`config.py` + `ci2lab.yaml`): modelo default `qwen2.5-coder:7b`, URL Ollama, cwd/workspace, flags por defecto.
2. **Errores Ollama accionables** en `run_agent` / `LLMClient`: distinguir conexión, HTTP, modelo missing; sugerir `ci2lab doctor`; considerar exit code ≠ 0.
3. **Revisar política fenced en native**: pasar `native_calls=None` cuando la lista está vacía, o intentar fenced como fallback si native no produjo calls.
4. **`--workspace` alias** de `--cwd` + documentación clara del sandbox.
5. **Blocklist mínima para bash** (o modo `shell=False` con split limitado) — diseño antes de código.
6. **Decisión explícita sobre write/edit**: deshabilitar dispatch hasta UX lista, o documentar como beta con confirmación.
7. **`run_logger.py`** para trazas JSON por ronda (prompt, tools, latencia, errores).
8. **Tests de integración** opcionales con Ollama mock HTTP.
9. **Implementar router/hardware/runtime** cuando se salga del MVP mono-modelo (fuera de alcance inmediato).

---

## Apéndice: mapa de imports críticos

```text
cli.py
  → pipeline.prepare_session
  → harness.run_agent, harness.repl.run_repl, harness.session.list_sessions

pipeline.py
  → contracts.types (HardwareProfile, ModelSelection)
  → harness.default_selection

harness/loop.py
  → contracts.types (ModelSelection, HardwareProfile)
  → harness.llm_client, messages, parsing, prompts, session, tools.registry, types

harness/llm_client.py
  → contracts.types.ModelSelection

harness/tools/registry.py
  → harness.tools.bash, filesystem, permissions, types
```

Este mapa resume **qué archivo llama a qué** en el camino crítico CLI → respuesta del agente.

---

## 16. Actualización — fase de saneamiento

**Fecha:** 2026-06-09

Cambios aplicados sin alterar la arquitectura ReAct ni implementar router/hardware/runtime.

### Implementado

| Tarea | Archivos | Notas |
|-------|----------|-------|
| `config.py` + `ci2lab.yaml` | `ci2lab/config.py` | Prioridad CLI > env > yaml > defaults; parser YAML mínimo sin deps |
| `--workspace` | `ci2lab/cli.py` | Alias de `--cwd`; error si ambos |
| Blocklist `bash` | `harness/tools/bash_safety.py` | Aplica antes de confirmación y con `--yes` |
| Errores Ollama | `harness/llm_errors.py`, `llm_client.py`, `loop.py`, `cli.py` | `LLMConnectionError` (exit 2), `LLMModelNotFoundError` (exit 3) |
| Fallback fenced/native | `harness/parsing.py` | Lista vacía de native → XML/fenced |
| `write_file` / `edit_file` | — | Modo supervisado — `WRITE_POLICY.md`, `write_edit_tools_status.md` |

### Modelo por defecto

Se mantiene **`llama3.1:8b`**. No se migró a Qwen en esta fase.

### Configuración

Archivos buscados: `./ci2lab.yaml`, `./ci2lab.yml`, `./ci2lab.json`, `~/.ci2lab/ci2lab.yaml`, o ruta en `CI2LAB_CONFIG`.

Variables de entorno: `CI2LAB_MODEL`, `CI2LAB_OLLAMA_URL`, `CI2LAB_BACKEND_URL`, `CI2LAB_TOOL_MODE`, `CI2LAB_MAX_ROUNDS`, `CI2LAB_WORKSPACE` / `CI2LAB_CWD`, `CI2LAB_STREAM`, `CI2LAB_YES` / `CI2LAB_AUTO_CONFIRM`.

### Pendiente tras saneamiento (superado parcialmente en fases posteriores)

- ~~Diff preview~~ → ✅ implementado (ver `write_edit_tools_status.md`)
- Git rollback — pendiente
- Router, hardware profiler, MCP, UI — pendiente

---

## 17. Actualización — logging estructurado (`runs/`)

**Fecha:** 2026-06-09

| Componente | Estado |
|------------|--------|
| `harness/run_logger.py` | ✅ |
| Artefactos por ejecución | `run_summary.json`, `conversation.json`, `tool_calls.jsonl`, `final_answer.md`, `config_snapshot.json` |
| CLI `--runs-dir`, `--no-log` | ✅ |
| Default logging activo | ✅ en `runs/` |
| Fallos de log no rompen agente | ✅ aviso amarillo |
| Documentación | [`run_logging.md`](run_logging.md), [`manual_tests.md`](../manual_tests.md) |

Detalle completo en [`docs/audits/run_logging.md`](run_logging.md).

---

## 18. Cierre de hito — validación mock/live

**Fecha:** 2026-06-09

| Entrega | Estado |
|---------|--------|
| Mock evals 7/7 | ✅ |
| Live evals 7/7 (`llama3.1:8b`) | ✅ |
| `pytest` | ✅ 64 passed |
| `ci2lab/evals/` | ✅ runner mock/live |
| Diff preview write/edit | ✅ |
| `run_logger.py` + `runs/` | ✅ |
| `config.py` + `ci2lab.yaml` | ✅ |

**Documentos de cierre:** [`live_eval_status.md`](live_eval_status.md), [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md), [`regression_checklist.md`](../regression_checklist.md).

**Decisión:** el harness agéntico queda como base funcional validada; hardware/router/runtime son la siguiente fase del producto, no de este hito.
