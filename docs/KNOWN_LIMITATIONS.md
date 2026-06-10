# Limitaciones conocidas — Ci2Lab (2026-06-10)

Este documento resume lo que **no** está implementado, qué riesgos permanecen y qué gaps de integración existen.

## Integración pipeline ↔ router

| Limitación | Detalle |
|------------|---------|
| Router no conectado a `chat`/`agent` | `prepare_session()` en `pipeline.py` intenta importar `ci2lab.hardware.profiler` y `ci2lab.runtime.ensure`, que no existen. Cae en `default_selection()` con `tool_mode: native` siempre. |
| `--model` ignora catálogo en chat | Al forzar un tag Ollama no catalogado (p. ej. `deepseek-coder:6.7b-instruct`), no se aplica el `tool_mode` del catálogo. |
| Sin auto-pull | `runtime/ensure.py` no existe; el usuario debe hacer `ollama pull` manualmente. |

**Workaround:** pasar `--tool-mode fenced` explícitamente para modelos que no soportan native tools. Ver README.

## Fuera de alcance

| Área | Estado |
|------|--------|
| Runtime automático (`ollama pull` / ensure) | No implementado |
| Git snapshot / rollback | No implementado |
| Auto-commit | No implementado |
| MCP | No implementado |
| UI / IDE integrada | No implementado |
| Routing multi-modelo por turno | No implementado |
| Benchmark live por modelo del catálogo | No implementado (solo scores estáticos en `models.json`) |
| `prefer_installed` en `resolve_model` | Parámetro ignorado |

## Seguridad y sandbox

| Limitación | Detalle |
|------------|---------|
| `bash` con `shell=True` | Mitigado con confirmación interactiva, blocklist mínima; `--yes` no omite blocklist |
| Sin sandbox avanzado | No hay contenedores, seccomp ni restricción de red para tools |
| Rutas | `resolve_path()` confina al `workspace`; symlinks no auditados en profundidad |
| Edición en disco | `write_file` / `edit_file` en modo supervisado (diff preview + aprobación); ver [`WRITE_POLICY.md`](WRITE_POLICY.md) |

## Operación y calidad del harness

| Limitación | Detalle |
|------------|---------|
| Modelo único validado en live evals | `llama3.1:8b`; otros modelos pueden fallar en tool use (JSON como texto, parámetros incorrectos) |
| Parser estricto | No parsea tool calls en bloques ` ```json `; solo native API, XML, o fences con nombre de tool |
| Runs "success" sin tools | Si el modelo responde con texto pero no ejecuta herramientas, el run puede marcarse como éxito |
| Errores streaming opacos | Errores HTTP de Ollama en modo stream pueden mostrar mensaje genérico de httpx |
| Live evals no deterministas | El modelo puede parafrasear, rechazar o elegir otra tool |
| Trim de contexto grosero | Estimación ~4 caracteres/token en `trim_messages()` |
| REPL / sesiones | Persistencia en `~/.ci2lab/sessions/` sin validación fuerte al reanudar `cwd` |
| CLI: flags solo en parser raíz | `--model` después de `chat` falla; debe ir antes del subcomando |

## Qué sí está cubierto

| Área | Estado |
|------|--------|
| Harness agéntico (ReAct, 7 tools, REPL, sesiones) | ✅ Validado (mock 7/7, live 7/7 con `llama3.1:8b`) |
| Hardware profiler | ✅ `ci2lab hardware` |
| Router (catálogo, intención, scoring, resolve) | ✅ CLI `ci2lab models …`; no integrado en chat |
| Catálogo `models.json` | ✅ 21 modelos |
| Logging en `runs/` | ✅ |
| Edición supervisada | ✅ |
| Tests automatizados | ✅ 70 passed |

Ver también [Validación live](audits/live_eval_status.md), [Política de edición](WRITE_POLICY.md) y [Checklist de regresión](regression_checklist.md).
