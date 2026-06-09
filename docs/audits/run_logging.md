# Logging estructurado de ejecuciones (runs/)

**Fecha:** 2026-06-09  
**Módulo:** `ci2lab/harness/run_logger.py`

## Objetivo

Persistir cada ejecución del agente en una carpeta bajo `runs/` sin alterar el comportamiento funcional del bucle ReAct. Los fallos de escritura emiten un aviso y no interrumpen la ejecución.

## Activación

| Mecanismo | Default |
|-----------|---------|
| Comportamiento por defecto | Logging **activado** |
| `--no-log` (CLI) | Desactiva |
| `CI2LAB_NO_LOG=1` | Desactiva |
| `no_log: true` en `ci2lab.yaml` | Desactiva |
| `log_runs: false` en `ci2lab.yaml` | Desactiva |

Directorio base:

- Default: `runs/`
- `--runs-dir <path>` o `CI2LAB_RUNS_DIR` o `runs_dir` en yaml

## Estructura de carpeta

```text
runs/
  2026-06-09_143022_a1b2c3d4/
    run_summary.json
    conversation.json
    tool_calls.jsonl
    final_answer.md
    config_snapshot.json
```

Nombre: `YYYY-MM-DD_HHMMSS_<short_id>` (hora local + 8 hex).

## Artefactos

### `run_summary.json`

Metadatos de la ejecución: timestamps, duración, modelo, `backend_url`, `tool_mode`, `workspace`, `max_rounds`, `stream`, `auto_confirm`, rondas, conteo de tools, `tools_used`, `status`, `error` si aplica.

**Status:** `success` | `llm_error` | `max_rounds` | `interrupted`

### `conversation.json`

```json
{ "messages": [ /* historial interno compatible con el bucle */ ] }
```

Incluye `system`, `user`, `assistant` (con `tool_calls` si aplica) y `tool`.

### `tool_calls.jsonl`

Una línea JSON por invocación:

- `round`, `tool_call_id`, `tool`, `arguments`
- `started_at`, `ended_at`, `duration_ms`
- `ok` (inverso de `is_error`)
- `output` (truncado a 2000 caracteres en el log)
- `error` si la tool falló
- `outcome` (`approved`, `denied`, `blocked_by_config`, `failed`; relevante en `write_file` / `edit_file`)

### `final_answer.md`

Texto final devuelto por `run_agent`.

### `config_snapshot.json`

Config efectiva sin secretos: bloques `resolved` (CLI/env/yaml) y `selection` (`ModelSelection`).

## Integración

```text
cli._build_config() → AgentConfig(run_log_enabled, runs_dir, config_snapshot)
  ↓
loop.run_agent() → RunLogger.maybe_create() → start()
  ↓
por cada tool → record_tool_call() → append tool_calls.jsonl
  ↓
finally → finalize() → resto de artefactos
```

## Seguridad y privacidad

- No se vuelcan variables de entorno completas.
- `config_snapshot` solo incluye campos de configuración conocidos.
- El output de tools en el log está truncado.

## Tests automatizados

Ver `tests/test_run_logger.py`.
