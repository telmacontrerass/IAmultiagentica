# Política de edición supervisada

## Estado

`write_file` y `edit_file` están **habilitadas y validadas**, pero solo en **modo supervisado**.

No son el flujo principal del agente sobre el código del repositorio ni constituyen edición autónoma: cada cambio en disco requiere revisión y aprobación explícita del usuario cuando `require_diff_preview=true` (valor por defecto).

## Qué significa modo supervisado

- Siempre se genera diff preview si `require_diff_preview=true`.
- El usuario debe aprobar el diff visualmente (`[s/N]`).
- `--yes` **no omite** el preview con `require_diff_preview=true`.
- Los cambios quedan registrados en `runs/` (`tool_calls.jsonl` con `outcome`).
- Se pueden desactivar por completo con `write_tools_enabled=false`.

Detalle técnico del flujo: [`docs/audits/write_edit_tools_status.md`](audits/write_edit_tools_status.md).

## Uso recomendado ahora

- Archivos temporales y workspaces de prueba.
- Configs de prueba o fixtures locales.
- Cambios pequeños y acotados.
- Evals (`005`, `006`, `007`) y validación del harness.
- Prototipos controlados fuera del código crítico del producto.

## Uso no recomendado todavía

- Edición masiva de código del repo real como flujo principal del agente.
- Refactors grandes sin revisión humana línea a línea.
- Cambios críticos en producción o en rutas sensibles sin revisar el diff.
- Scripts automatizados con `require_diff_preview=false` (omite la barrera de supervisión).

## Pendiente antes de edición intensiva

- Git snapshot / rollback antes de aplicar cambios.
- Más evals de edición sobre código real.
- Mejor política por tipo de archivo (allowlist/denylist de rutas).
- Posible modo dry-run adicional.

## Referencias

- [Estado técnico write/edit](audits/write_edit_tools_status.md)
- [Validación en evals mock/live](audits/live_eval_status.md) — tareas `005`–`007`
- [Limitaciones conocidas](KNOWN_LIMITATIONS.md)
