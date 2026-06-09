# Estado de `write_file` y `edit_file`

**Fecha:** 2026-06-09 (actualizado: política de edición supervisada)  
**Fase:** edición habilitada en modo supervisado — **validado** en evals `005`/`006`/`007` mock y live

## Resumen

`write_file` y `edit_file` están **habilitadas y validadas** en **modo supervisado**: diff preview obligatorio por defecto antes de modificar el disco. El usuario ve un diff unificado (o preview de archivo nuevo) y debe aprobar. `--yes` **no omite** el preview si `require_diff_preview=true`.

**Decisión actual:** edición disponible, no autónoma. Cada cambio requiere supervisión humana; no es el flujo principal del agente sobre el código crítico del repositorio. Política completa: [`docs/WRITE_POLICY.md`](../WRITE_POLICY.md). Desactivar por completo con `write_tools_enabled: false`.

## Configuración

| Campo | Default | Descripción |
|-------|---------|-------------|
| `write_tools_enabled` | `true` | Si `false`, write/edit devuelven error sin ejecutar |
| `require_diff_preview` | `true` | Si `true`, siempre muestra diff y pide confirmación |

Fuentes: `ci2lab.yaml`, `CI2LAB_WRITE_TOOLS_ENABLED`, `CI2LAB_REQUIRE_DIFF_PREVIEW`, `AgentConfig`.

Cuando `require_diff_preview=false`, write/edit siguen el flujo de confirmación estándar (`--yes` puede auto-aprobar).

## Flujo

1. Modelo invoca `write_file` o `edit_file`.
2. Si `write_tools_enabled=false` → `outcome: blocked_by_config`.
3. Se genera preview (`harness/tools/write_preview.py`):
   - **edit_file:** diff unificado antes/después del reemplazo.
   - **write_file (existente):** diff contenido actual vs nuevo.
   - **write_file (nuevo):** mensaje de creación + preview del contenido.
4. Si validación falla (p. ej. `old_string` no encontrado) → `outcome: failed` sin tocar disco.
5. Si `require_diff_preview=true` → panel Rich con diff → confirmación `[s/N]`.
6. Si deniega → `outcome: denied`, archivo sin cambios.
7. Si aprueba → ejecuta y `outcome: approved`.

`bash` no usa diff preview; `--yes` sigue auto-confirmando bash (salvo blocklist).

## Logging (`tool_calls.jsonl`)

Cada invocación de write/edit registra `outcome`:

- `approved`
- `denied`
- `blocked_by_config`
- `failed`

## Inventario en código

| Ubicación | `write_file` | `edit_file` |
|-----------|--------------|-------------|
| `TOOL_NAMES` / `_DISPATCH` | ✅ | ✅ |
| `write_preview.py` | ✅ | ✅ |
| `write_permissions.py` | ✅ | ✅ |
| `CONFIRM_TOOLS` (modo sin preview) | ✅ | ✅ |

## Fuera de alcance

- Git rollback / auto-commit
- Diff preview para `bash`
- UI gráfica
