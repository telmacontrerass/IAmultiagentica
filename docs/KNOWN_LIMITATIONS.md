# Limitaciones conocidas — Ci2Lab harness (hito 2026-06-09)

Este documento resume lo que **no** está implementado o qué riesgos permanecen tras cerrar el hito del arnés agéntico local.

## Fuera de alcance del hito actual

| Área | Estado |
|------|--------|
| Hardware profiler (`ci2lab/hardware/`) | No implementado — solo esqueleto |
| Router de modelos (`ci2lab/router/`) | No implementado — solo esqueleto |
| Catálogo de modelos (`catalog/`, `models.json`) | No existe |
| Runtime automático (`ci2lab/runtime/`, `ollama pull`) | No implementado |
| Git snapshot / rollback | No implementado |
| Auto-commit | No implementado |
| MCP | No implementado |
| UI / IDE integrada | No implementado |
| Routing multi-modelo | No implementado |
| Benchmark de calidad de modelos | No implementado |

## Seguridad y sandbox

| Limitación | Detalle |
|------------|---------|
| `bash` con `shell=True` | Mitigado con confirmación interactiva, blocklist mínima y `--yes` no omite blocklist; no hay allowlist ni sandbox de procesos |
| Sin sandbox avanzado | No hay contenedores, seccomp ni restricción de red para tools |
| Rutas | `resolve_path()` confina al `workspace`; symlinks no auditados en profundidad |
| Edición en disco | `write_file` / `edit_file` **habilitadas en modo supervisado** (diff preview + aprobación); no es edición autónoma ni flujo principal sobre código crítico del repo; ver [`WRITE_POLICY.md`](WRITE_POLICY.md) |

## Operación y calidad

| Limitación | Detalle |
|------------|---------|
| Modelo único validado en live | `llama3.1:8b`; otros modelos pueden comportarse distinto en tool use |
| Live evals no deterministas | El modelo puede parafrasear, rechazar o elegir otra tool; las tareas usan criterios flexibles donde aplica |
| Sin logging estructurado JSON por ronda | Existe logging en `runs/` pero no `run_logger` avanzado por evento |
| Trim de contexto grosero | Estimación ~4 caracteres/token en `trim_messages()` |
| REPL / sesiones | Persistencia en `~/.ci2lab/sessions/` sin validación fuerte al reanudar `cwd` |

## Qué sí está cubierto

Para el alcance del harness MVP, ver [Estado de validación live](audits/live_eval_status.md), [Política de edición supervisada](WRITE_POLICY.md) y [Checklist de regresión](regression_checklist.md).
