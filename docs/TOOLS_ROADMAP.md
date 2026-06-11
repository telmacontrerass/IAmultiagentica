# Hoja de ruta de herramientas Ci2Lab

## Estado actual (10 herramientas)

| Herramienta | Tipo | Workspace | Secret policy | Confirmación |
|-------------|------|-----------|---------------|--------------|
| `read_file` | lectura | `resolve_path` | bloquea | no |
| `ls` | listado | `resolve_path` | no aplica | no |
| `glob` | búsqueda | `resolve_path` | no aplica | no |
| `grep` | búsqueda | `resolve_path` | omite/bloquea | no |
| `file_info` | inspección | `resolve_path` | metadatos sin contenido | no |
| `tree` | inspección | `resolve_path` | omite sensibles | no |
| `inspect_file` | lectura acotada | `resolve_path` | bloquea | no |
| `write_file` | escritura | `resolve_path` | no | sí (preview) |
| `edit_file` | escritura | `resolve_path` | no | sí (preview) |
| `bash` | ejecución | workspace guard | no | sí (`--yes` no salta guards) |

**Arquitectura:** `registry.py` define `TOOL_NAMES`, schemas OpenAI y `_DISPATCH` → `execute_tool()`. Rutas vía `paths.resolve_path`. Secretos vía `secret_files.is_sensitive_path`. Outcomes en `policy.outcome_for_tool_output`. Tests en `tests/test_*`.

---

## Tabla de candidatas

### 1. Inspección segura

| Tool | Utilidad | Riesgo | vs bash | Workspace | Secret policy | Timeout | Límite salida | Tests | Decisión |
|------|----------|--------|---------|-----------|---------------|---------|---------------|-------|----------|
| `file_info` | Alta — metadatos sin leer | Bajo | Sí | Sí | metadatos only | No | Bajo | 5+ | **Fase 1 — hecho** |
| `tree` | Alta — overview repo | Bajo | Sí | Sí | omite sensibles | No | depth/entries | 4+ | **Fase 1 — hecho** |
| `inspect_file` | Alta — peek acotado | Bajo | Sí | Sí | bloquea | No | max_lines | 6+ | **Fase 1 — hecho** |
| `git_status` | Media — estado repo | Bajo | Parcial | Sí (cwd) | N/A | Sí (git) | Medio | 3+ | **Fase 2** |
| `diff` | Media — cambios locales | Bajo | Parcial | Sí | omitir .env en paths | Sí | Alto | 4+ | **Fase 2** |

### 2. Ejecución controlada

| Tool | Utilidad | Riesgo | vs bash | Workspace | Secret policy | Timeout | Tests | Decisión |
|------|----------|--------|---------|-----------|---------------|---------|-------|----------|
| `run_tests` | Alta | Medio | Sí — comando fijo | Sí | N/A | Sí | 4+ | **Fase 2** |
| `validate_project` | Media | Medio | Sí — orquestación | Sí | N/A | Sí | 3+ | **Fase 3** |
| `run_python_file` | Media | Medio-alto | Parcial | Sí (path script) | N/A | Sí | 5+ | **Fase 3** |

### 3. Edición robusta

| Tool | Utilidad | Riesgo | vs bash | Workspace | Secret policy | Tests | Decisión |
|------|----------|--------|---------|-----------|---------------|-------|----------|
| `apply_patch` | Alta | Medio | Sí | Sí | preview paths | 6+ | **Fase 3** |
| `read_json` / `write_json` | Media | Medio | Parcial | Sí | bloquear sensibles | 4+ | **Fase 3** |
| `read_yaml` / `write_yaml` | Media | Medio | Parcial | Sí | bloquear sensibles | 4+ | **Fase 3** (requiere dep o parser mínimo) |

### 4. Peligrosas / más adelante

| Tool | Decisión |
|------|----------|
| `pip_install` | **Nunca por ahora** — red + supply chain |
| `git_commit` | **Fase 4+** — mutación irreversible |
| `web_search` | **Nunca por ahora** — red |
| `browser` | **Nunca por ahora** — red + superficie enorme |
| Shell libre ampliado | **No** — `bash` actual + guards es suficiente |

---

## Fases recomendadas

### Fase 1 — Inspección (esta PR)

`file_info`, `tree`, `inspect_file` — sin red, sin escritura, sin subprocess.

### Fase 2 — Git + tests acotados

`git_status`, `diff`, `run_tests` — subprocess con allowlist de comandos, timeout, cwd=workspace.

### Fase 3 — Edición y validación

`apply_patch`, JSON helpers, `validate_project`, `run_python_file` — reutilizar write preview y secret policy.

### Fase 4+ — Solo con diseño explícito

`git_commit`, integraciones externas.

---

## Primera PR recomendada

**Implementada:** módulo `ci2lab/harness/tools/inspection.py`, registro en `registry.py`, prompts, `tests/test_inspection_tools.py`.

---

## Descartadas explícitamente (por ahora)

- Red: `web_search`, `browser`, `pip_install`
- Git write: `git_commit`, `git_push`
- Herramientas que duplican `bash` sin valor añadido (p. ej. `run_command` genérico)
- Lectura de secretos “con máscara” — política actual es bloqueo total en `read_file`/`inspect_file`/`grep`
