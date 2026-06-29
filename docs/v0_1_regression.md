# CI2Lab v0.1 Regression Gate

## 1. Objetivo

Esta puerta de regresion define el minimo que debe seguir funcionando antes de cerrar CI2Lab v0.1 como un arnes local seguro, auditable y util para tareas de codigo/documentos con herramientas.

La intencion no es cubrir todo el repositorio ni validar cada integracion experimental. Es fijar una linea base ejecutable para las garantias centrales: CLI, loop clasico, herramientas auditadas, seguridad determinista, escritura supervisada, trazabilidad de runs y multiagente opcional conservador.

## 2. Alcance

Entra en esta puerta:

- CLI basica: ayuda global, `doctor`, shortcut de `agent`, modo multiagente desde CLI.
- Agente clasico: loop ReAct, parsing/ejecucion de herramientas, cache, nudges, cierre conservador.
- Herramientas auditadas: lectura de archivos/documentos, grep, escritura, edicion, patch, git evidence.
- Seguridad de workspace, secretos y bash: path confinement, blocklist, `--yes` sin bypass, vectores Windows.
- Escritura supervisada: preview/diff, confirmacion, writes bloqueados, apply_patch.
- Run logging: carpetas de run, resumen, tool calls, tokens, `--no-log`.
- Permisos: engines, perfiles, aprobaciones de sesion y reglas basicas allow/ask/deny.
- Multiagente opcional conservador: intent routing, allowlists por rol, prompts, trazas, validacion, scope y evidencia minima.
- Evals/redteam ya existentes: mock evals y regresiones puntuales de seguridad.

Queda fuera de esta puerta:

- UI como superficie estable de v0.1.
- MCP avanzado como core estable.
- Web/skills como core estable.
- Sandbox de sistema operativo, contenedores o aislamiento fuerte de procesos.
- Validacion semantica completa de programas generados.
- Rendimiento, latencia y consumo de memoria.
- Calidad real de respuestas de todos los modelos locales.
- Evals live con Ollama u otros servicios externos.

## 3. Comando recomendado

Ejecutar desde PowerShell en la raiz del repositorio:

```powershell
$env:TEMP = "$PWD\.pytest-tmp"
$env:TMP = "$PWD\.pytest-tmp"

python -m pytest `
  tests/test_cli_help.py `
  tests/test_cli_doctor.py `
  tests/test_pipeline.py `
  tests/test_harness_loop.py `
  tests/test_harness_tools.py `
  tests/test_write_preview.py `
  tests/test_write_file_intent_policy.py `
  tests/test_apply_patch.py `
  tests/test_workspace_security.py `
  tests/test_security_core.py `
  tests/test_secret_files_policy.py `
  tests/test_secret_files_v02.py `
  tests/test_bash_safety.py `
  tests/test_bash_redirect.py `
  tests/test_bash_windows_vectors.py `
  tests/test_security_engine.py `
  tests/test_security_profiles.py `
  tests/test_session_permissions.py `
  tests/test_run_logger.py `
  tests/test_multiagent_intent.py `
  tests/test_multiagent_runner.py `
  tests/test_multiagent_orchestrator.py `
  tests/test_multiagent_tooling.py `
  tests/test_multiagent_cli.py `
  tests/test_evals.py `
  tests/redteam/test_redteam_findings.py
```

Para validar que la lista sigue apuntando a tests existentes sin ejecutar la puerta completa:

```powershell
$env:TEMP = "$PWD\.pytest-tmp"
$env:TMP = "$PWD\.pytest-tmp"

python -m pytest --collect-only -q `
  tests/test_cli_help.py `
  tests/test_cli_doctor.py `
  tests/test_pipeline.py `
  tests/test_harness_loop.py `
  tests/test_harness_tools.py `
  tests/test_write_preview.py `
  tests/test_write_file_intent_policy.py `
  tests/test_apply_patch.py `
  tests/test_workspace_security.py `
  tests/test_security_core.py `
  tests/test_secret_files_policy.py `
  tests/test_secret_files_v02.py `
  tests/test_bash_safety.py `
  tests/test_bash_redirect.py `
  tests/test_bash_windows_vectors.py `
  tests/test_security_engine.py `
  tests/test_security_profiles.py `
  tests/test_session_permissions.py `
  tests/test_run_logger.py `
  tests/test_multiagent_intent.py `
  tests/test_multiagent_runner.py `
  tests/test_multiagent_orchestrator.py `
  tests/test_multiagent_tooling.py `
  tests/test_multiagent_cli.py `
  tests/test_evals.py `
  tests/redteam/test_redteam_findings.py
```

## 4. Matriz de cobertura

| Area v0.1 | Tests incluidos | Que protege | Riesgo si falla |
|---|---|---|---|
| CLI | `tests/test_cli_help.py`, `tests/test_cli_doctor.py`, `tests/test_multiagent_cli.py` | Ayuda global, doctor, shortcuts, activacion de multiagente. | El producto puede no arrancar o mostrar rutas de uso rotas. |
| Loop clasico | `tests/test_harness_loop.py`, `tests/test_pipeline.py` | ReAct loop, progreso, herramientas, cache, nudges, contratos simples, seleccion/config basica. | El arnes clasico puede aceptar resultados sin evidencia, atascarse o romper flujo de herramientas. |
| Herramientas de archivo | `tests/test_harness_tools.py` | Lectura de archivos, PDFs, DOCX/XLSX, grep, normalizacion de argumentos, roundtrip basico. | Tareas de codigo/documentos dejan de ser fiables. |
| Escritura supervisada | `tests/test_write_preview.py`, `tests/test_write_file_intent_policy.py`, `tests/test_apply_patch.py` | Preview/diff, aprobacion/denegacion, write tools disabled, paths sensibles, patch. | El agente podria escribir sin supervision suficiente o no escribir cuando debe. |
| Seguridad workspace | `tests/test_workspace_security.py`, `tests/test_security_core.py` | Bloqueo de rutas externas, traversal, symlink, `--yes` sin bypass, audit deny. | Se rompe la garantia central de confinamiento al workspace. |
| Secretos | `tests/test_secret_files_policy.py`, `tests/test_secret_files_v02.py` | Bloqueo de secretos reales, grep seguro, falsos positivos controlados. | El agente podria leer o filtrar credenciales obvias. |
| Bash safety | `tests/test_bash_safety.py`, `tests/test_bash_redirect.py`, `tests/test_bash_windows_vectors.py` | Blocklist destructiva, bash->tool redirect, vectores Windows externos. | Comandos peligrosos o escapes por shell podrian ejecutarse. |
| Permisos | `tests/test_security_engine.py`, `tests/test_security_profiles.py`, `tests/test_session_permissions.py` | Engines, perfiles, hard guards, reglas ask/deny/allow, aprobaciones de sesion. | `--yes`, perfiles o reglas podrian relajar garantias sin querer. |
| Run logging | `tests/test_run_logger.py` | Creacion de runs, resumen, tool_calls, token usage, `--no-log`, tolerancia a fallo de logging. | Se pierde trazabilidad o el logging rompe ejecuciones. |
| Multiagente intent | `tests/test_multiagent_intent.py` | Routing determinista, scope constraints, no-write global, dangerous ops. | El orquestador puede correr fases equivocadas o permitir writes donde no toca. |
| Multiagente runner/orchestrator | `tests/test_multiagent_runner.py`, `tests/test_multiagent_orchestrator.py`, `tests/test_multiagent_cli.py` | Allowlists por rol, prompts, role anchors, secuencia, reparacion, estados finales, trazas. | El multiagente puede ampliar herramientas, ocultar fallos o reportar `completed` indebidamente. |
| Multiagente tooling/validacion | `tests/test_multiagent_tooling.py` | Evidencia de tool calls, role violations, readback, artifact validation, scope, git evidence, anti-hallucination. | Runs multiagente pueden aceptar narrativa sin evidencia o cambios fuera de scope. |
| Evals/redteam | `tests/test_evals.py`, `tests/redteam/test_redteam_findings.py` | Evals mock, expected/forbidden tools, findings de seguridad conocidas. | Regresiones ya descubiertas pueden volver sin alarma. |

## 5. Criterios de aceptacion

La puerta se considera pasada cuando:

- Todos los tests del comando recomendado pasan en el entorno local objetivo.
- No hay cambios productivos no intencionados en `git status`.
- No se relajan reglas de seguridad de workspace, secretos, bash, perfiles o permisos para hacer pasar tests.
- No se aceptan runs multiagente sin evidencia minima de herramientas cuando la tarea exige escritura, validacion o scope.
- No se degradan trazas de run: tool calls, status, errores y final answer deben seguir siendo auditables.
- Si una prueba falla por limitacion conocida del entorno, se documenta en una seccion de incidencias del release candidate antes de declarar v0.1 estable.

Plantilla minima para incidencias:

```text
Incidencia:
- Test:
- Entorno:
- Sintoma:
- Causa probable:
- Decision: blocker / aceptado con limitacion / falso positivo pendiente
- Seguimiento:
```

## 6. Criterios de exclusion

Esta suite no valida:

- Rendimiento, latencia ni escalabilidad.
- Calidad semantica del modelo o correccion profunda de programas generados.
- Robustez con todos los modelos locales del catalogo.
- Seguridad de sistema operativo, sandbox real, contenedores o aislamiento de red.
- Integraciones experimentales avanzadas: UI estable, MCP avanzado, web/skills como superficie core.
- Evals live con Ollama, disponibilidad de modelos o `ollama pull`.
- Casos de documentos complejos que requieran OCR, conversion perfecta o maquetacion fiel.
- Ausencia total de falsos positivos en las heuristicas multiagente.

## 7. Proximo paso recomendado

El siguiente paso deberia ser crear un envoltorio ejecutable para esta puerta, por ejemplo `scripts/run_v0_1_regression.py`, que:

- ejecute exactamente el comando de esta pagina;
- configure `TEMP`/`TMP` dentro del workspace en Windows;
- imprima resumen por area;
- guarde salida bajo `runs/v0_1_regression/`;
- falle con codigo distinto de cero si falla cualquier test.

El primer envoltorio ya existe. Pendiente para una iteracion posterior: guardar reportes bajo `runs/v0_1_regression/` e imprimir resumen por area a partir del resultado real de pytest.

## 8. Script ejecutable

La puerta puede ejecutarse con:

```powershell
python scripts/run_v0_1_regression.py
```

Para validar solo la recoleccion:

```powershell
python scripts/run_v0_1_regression.py --collect-only
```

Para listar los tests incluidos:

```powershell
python scripts/run_v0_1_regression.py --list
```
