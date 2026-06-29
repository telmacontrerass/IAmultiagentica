# CI2Lab v0.1 Release Candidate Report

## 1. Resultado general

- Comando ejecutado: `python scripts/run_v0_1_regression.py`
- Fecha/hora aproximada: 2026-06-29 12:30:49 +02:00
- Tests recolectados: 428
- Resultado final: 426 passed, 2 skipped, 1 warning
- Exit code: 0

La regression gate v0.1 completa paso correctamente.

## 2. Areas cubiertas

- CLI: ayuda global, `doctor`, shortcuts y activacion de multiagente.
- Loop clasico: loop ReAct, progreso, cache, nudges, contratos simples y configuracion base.
- Herramientas: lectura de archivos/documentos, PDF/DOCX/XLSX, grep y normalizacion.
- Escritura supervisada: preview/diff, aprobacion/denegacion, write tools disabled y `apply_patch`.
- Seguridad: workspace confinement, traversal, symlink, secretos, bash blocklist y vectores Windows.
- Permisos: engines, perfiles, hard guards, reglas allow/ask/deny y aprobaciones de sesion.
- Run logging: carpetas de run, resumen, tool calls, token usage y `--no-log`.
- Multiagente: intent routing, allowlists por rol, prompts, trazas, estados, validacion, scope y evidencia.
- Evals/redteam: evals mock y regresiones de seguridad puntuales.

## 3. Tests fallidos

No hay tests fallidos en la regression gate v0.1.

## 4. Warnings o skips relevantes

- Warning: `PytestCacheWarning` al intentar crear `C:\Users\jaciv\Desktop\IAmultiagentica\.pytest_cache\v\cache\nodeids`, con `[WinError 5] Acceso denegado`. No afecta al resultado de la gate; los tests terminaron con exit code 0.
- Skip condicional en `tests/test_security_core.py::test_symlink_outside_workspace` cuando Windows no permite crear symlinks o no se puede crear el enlace.
- Skip marcado en `tests/test_bash_windows_vectors.py::test_start_process_without_path_not_blocked`; documenta que `Start-Process` sin ruta externa explicita no se bloquea por esa regla.

## 5. Estado de git

Salida de `git status --short` tras ejecutar la gate:

```text
 M ci2lab/harness/multiagent/orchestrator.py
 M tests/test_multiagent_tooling.py
?? .claude/
?? .pytest-tmp/
?? docs/v0_1_regression.md
?? docs/v0_1_status.md
?? notes/
?? scripts/run_v0_1_regression.py
```

Notas:

- `ci2lab/harness/multiagent/orchestrator.py` y `tests/test_multiagent_tooling.py` contienen cambios previos de la estabilizacion multiagente.
- `docs/v0_1_status.md`, `docs/v0_1_regression.md`, `scripts/run_v0_1_regression.py` y este informe son artefactos nuevos de preparacion v0.1.
- `.pytest-tmp/` fue usado para redirigir `TEMP`/`TMP` durante pytest.
- `git status` tambien emitio warnings de permiso al leer `C:\Users\jaciv/.config/git/ignore`; no afecto a la regression gate.

## 6. Conclusion

Estado recomendado: `ready_with_known_limitations`.

Motivo: la regression gate v0.1 pasa completa con exit code 0. Quedan limitaciones conocidas documentadas: no hay sandbox de sistema operativo, la validacion multiagente es conservadora y parcialmente heuristica, y existen warnings/skips esperables en Windows. Para demo local de v0.1, el estado es suficientemente bueno.

## 7. Siguiente paso recomendado

Preparar demos v0.1 basadas en los caminos que la gate protege:

- demo CLI clasica con lectura/escritura supervisada y run logging;
- demo de bloqueo de seguridad workspace/secretos/bash;
- demo multiagente opcional con evidencia, validacion y scope conservador.

Antes de publicar, actualizar la documentacion de usuario para declarar explicitamente las limitaciones aceptadas y separar superficies estables de integraciones experimentales.
