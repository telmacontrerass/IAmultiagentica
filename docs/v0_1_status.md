# CI2Lab v0.1 Status

## 1. Scope propuesto para v0.1

CI2Lab v0.1 deberia cubrir un arnes local, seguro y auditable para ejecutar agentes con herramientas sobre tareas de codigo y documentos, con CLI usable, permisos deterministas, trazas de runs y un flujo multiagente opcional pero conservador.

## 2. Componentes existentes

- CLI principal: `ci2lab/cli/main.py`, `ci2lab/cli/parser.py` y comandos en `ci2lab/cli/commands/`.
- Configuracion runtime: `ci2lab/cli/runtime.py`, `ci2lab/config.py`, `ci2lab/settings.py`, `ci2lab/pipeline.py`.
- Router/modelos/hardware: `ci2lab/router/`, `ci2lab/hardware/`, `ci2lab/catalog/models.json`.
- Loop del agente: `ci2lab/harness/query/loop.py`; `ci2lab/harness/loop.py` es alias de compatibilidad.
- Prompts del arnes: `ci2lab/harness/prompts.py` y plantillas en `ci2lab/harness/prompts/`.
- Parsing de herramientas: `ci2lab/harness/parsing.py` y `ci2lab/harness/parsing_parts/`.
- Registro y dispatch de herramientas: `ci2lab/harness/tools/registry.py`, `ci2lab/harness/tools/schemas.py`, `ci2lab/harness/tools/dispatch.py`.
- Ejecucion y permisos por tool call: `ci2lab/harness/tools/executor_parts/core.py`, `ci2lab/security/engine.py`.
- Herramientas de filesystem/documentos: `ci2lab/harness/tools/filesystem.py`, `ci2lab/harness/tools/filesystem_parts/`, `ci2lab/harness/tools/docx.py`, `ci2lab/harness/tools/convert.py`.
- Herramientas de shell/git/web/vision/MCP/skills: `ci2lab/harness/tools/bash.py`, `git_tools.py`, `web.py`, `vision_tool.py`, `skill_tool.py`, `ci2lab/harness/mcp/`.
- Seguridad de workspace, secretos y bash: `ci2lab/security/policy.py`, `ci2lab/security/paths.py`, `ci2lab/harness/tools/bash_safety.py`, `ci2lab/harness/tools/secret_files.py`.
- Motores de permisos: `ci2lab/security/engine.py`, `ci2lab/security/opencode_permissions.py`, `ci2lab/security/session_permissions.py`.
- Logging de runs: `ci2lab/harness/run_logger.py`.
- Sesiones/REPL: `ci2lab/harness/repl.py`, `ci2lab/harness/session.py`.
- Multiagente opcional: `ci2lab/harness/multiagent/intent.py`, `roles.py`, `runner.py`, `orchestrator.py`, `state.py`.
- UI local: `ci2lab/ui/` y assets en `ci2lab/ui/static/`.
- Evaluaciones: `ci2lab/evals/`, `evals/tasks/`, `scripts/run_harness_write_eval.py`.
- Documentacion existente: `README.md`, `docs/SECURITY_POLICY.md`, `docs/WRITE_POLICY.md`, `docs/KNOWN_LIMITATIONS.md`, `docs/evals.md`, `docs/audits/`.

Comandos CLI visibles en `ci2lab/cli/parser.py`:

- `ci2lab "request"` como atajo de `agent`.
- `ci2lab agent "request"`.
- `ci2lab chat`.
- `ci2lab menu`.
- `ci2lab --multi-agent chat`.
- `ci2lab tools <model>` y `<model> tools`.
- `ci2lab sessions [--json]`.
- `ci2lab skills [--json]`.
- `ci2lab doctor`.
- `ci2lab hardware [--json]`.
- `ci2lab models recommend|install|run`.
- `ci2lab evals run`.
- `ci2lab permissions ...`.
- `ci2lab ui`.

Herramientas registradas actualmente:

- Lectura/busqueda/inspeccion: `read_file`, `read_document`, `ls`, `glob`, `grep`, `file_info`, `tree`, `inspect_file`.
- Escritura/edicion: `write_file`, `edit_file`, `apply_patch`, `write_docx`, `notebook_edit`, `fill_docx_template`.
- Conversion/documentos: `docx_to_pdf`, `pdf_to_docx`.
- Ejecucion/revision: `bash`, `git_status`, `git_diff`.
- Workflow/interaccion: `todo_write`, `ask_user`, `delegate`, `skill`, `mcp_call`.
- Web/vision: `web_search`, `web_fetch`, `analyze_image`.

## 3. Que funciona

- CLI basica y comandos principales estan cableados y probados: `agent`, `chat`, `models`, `hardware`, `doctor`, `evals`, `sessions`, `skills`, `ui` y permisos.
- El loop ReAct ejecuta rondas con trimming/compaction, parsing de tool calls nativos/fenced/XML, cache de lecturas repetidas, nudges de recuperacion, limite de errores y cierre por `max_rounds`.
- El arnes registra runs en `runs/` con `config_snapshot.json`, `tool_calls.jsonl`, `token_usage.jsonl`, `conversation.json`, `final_answer.md` y `run_summary.json`.
- La politica de workspace bloquea lecturas/escrituras fuera del workspace y mantiene bloqueos aunque `--yes` este activo.
- La politica de secretos bloquea nombres sensibles reales y evita fugas por `grep`/lecturas.
- `bash` tiene una capa de seguridad adicional con blocklist para comandos destructivos, rutas externas y vectores Windows.
- La escritura supervisada (`write_file`, `edit_file`, `write_docx`, `apply_patch`) tiene preview/diff, confirmacion y tests.
- El motor por defecto `claude_experimental` combina hard guards con capa `deny`/`ask`/`allow` y aprobaciones de sesion.
- El motor legacy `ci2lab` sigue disponible y `opencode_experimental` esta aislado como modo de laboratorio.
- Hay herramientas documentales para PDF/DOCX/XLSX via `read_document`, `read_file`, `grep`, `write_docx`, `pdf_to_docx`, `docx_to_pdf`.
- El flujo multiagente secuencial existe como opcion: intent classifier, planner, researcher, coder, validator, reviewer y security reviewer.
- Los subagentes tienen allowlist por rol en `roles.py`, interseccion skill+rol en `runner.py` y prompts con allowlist efectiva.
- El multiagente persiste trazas de fases y evidencia de herramientas, incluyendo `allowed_tools`, `role_anchor`, previews y estado final.
- La validacion multiagente ya no acepta solo narrativa: exige evidencia de herramientas para writes, readback, `git_status`/`git_diff` cuando aplica, y detecta algunas violaciones de rol.
- Se ha empezado a validar artefactos escritos: readback de archivos escritos por coder, comprobacion minima de `.py` y deteccion de scope fuera de carpeta inferida.
- Existen evals mock y tareas JSON para comprobar uso esperado/prohibido de herramientas.

## 4. Que esta parcialmente implementado o fragil

- La promesa de "seguridad" sigue siendo de arnes local, no de sandbox de sistema operativo: no hay contenedor, seccomp, aislamiento de red ni rollback automatico.
- La clasificacion de intent y de scope multiagente es heuristica por marcadores de texto; funciona para casos cubiertos, pero puede fallar con prompts ambiguos o wording nuevo.
- El validator multiagente tiene validacion deterministica basica, pero no es un validador semantico de programas; `py_compile` solo detecta sintaxis/importabilidad, y el fallback sin `bash` usa patrones simples.
- El status multiagente depende de evidencia trazada y reglas conservadoras; es bueno para auditoria, pero puede producir falsos negativos si una herramienta falla por entorno o Git no esta disponible.
- `git_status`/`git_diff` son usados como evidencia de scope, pero esto depende de que el workspace sea repo Git o de que el entorno permita esos comandos.
- La matriz de herramientas por rol es estatica y no esta aun modelada como politica versionada/documentada para producto.
- `tool_trace_failed` existe como concepto en el flujo, pero no deberia ampliarse hasta cerrar contrato de estados y errores.
- La UI local existe, pero no parece ser el centro de v0.1 seguro/auditable; conviene no declarar paridad con CLI.
- MCP y skills existen, pero amplian la superficie de seguridad y deberian etiquetarse como extensibilidad controlada/experimental salvo tests de integracion mas fuertes.
- La configuracion tiene varias capas (`ci2lab.yaml`, settings, presets, flags, project memory, skills) que pueden confundir al usuario si v0.1 no fija un camino recomendado.
- El runtime no auto-instala modelos (`ollama pull` sigue manual, segun `docs/KNOWN_LIMITATIONS.md`).
- Algunas cadenas/documentacion muestran problemas de encoding en lecturas actuales, especialmente texto con acentos renderizado como mojibake; no parece bloquear funcionalidad, pero ensucia documentacion y diagnosticos.

## 5. Que falta para cerrar v0.1

### Producto/CLI

- Definir el camino feliz oficial de v0.1: instalacion, `doctor`, seleccion de modelo, primer `agent`, revision de run.
- Hacer explicito que `--multi-agent` es opcional y conservador, no modo por defecto.
- Revisar ayuda CLI y README para separar "estable v0.1" de "experimental/lab".
- Documentar presets recomendados de seguridad y workspace.
- Decidir si `ci2lab ui` entra en v0.1 como preview o como superficie soportada.

### Seguridad

- Mantener `claude_experimental` como default seguro y documentar sus garantias reales.
- Auditar que todos los path tools pasan por resolucion workspace/secret policy.
- Completar una matriz pequena de seguridad: read/write/bash/git/web/MCP por engine y perfil.
- Aclarar que `opencode_experimental` no es sandbox seguro.
- Revisar web tools y MCP como superficies de exfiltracion o ejecucion indirecta.

### Multiagente

- Documentar fases, roles, allowlists efectivas y estados finales.
- Congelar la matriz de herramientas por rol para v0.1.
- Convertir reglas recientes de validacion/scope en contrato documentado, no solo tests.
- Reducir dependencia de wording heuristico o, al menos, registrar en trace que heuristica activo una restriccion.
- Mantener reparaciones por coder solo cuando el fallo sea accionable, no por falta de evidencia externa.

### Validacion

- Definir niveles: readback minimo, check sintactico, comando de test enfocado, scope Git.
- Documentar cuando un run puede acabar `validation_failed` aunque el archivo exista.
- Anadir fixtures/evals para documentos y PDFs con salida esperada.
- Evitar que "missing git evidence" o entorno sin Git esconda fallos de artefactos, manteniendo estado conservador.
- Definir si `py_compile` via `bash` es suficiente para `.py` en v0.1 o si debe usarse una herramienta nativa dedicada.

### Runs/trazabilidad

- Documentar formato de `runs/` y `multiagent_trace.json`.
- Garantizar que fallos de logging no rompen el agente, pero quedan visibles.
- Anadir un comando CLI de inspeccion de ultimo run o resumen de evidencia.
- Definir retencion/limpieza de runs para repos reales.
- Corregir problemas de permisos de `.pytest_cache`/rutas locales si afectan entornos Windows habituales.

### Documentacion

- Crear un `docs/v0_1_user_guide.md` corto con flujo de uso.
- Crear un `docs/v0_1_security_model.md` con garantias y no-garantias.
- Actualizar `docs/KNOWN_LIMITATIONS.md` con multiagente, validacion y scope.
- Anadir ejemplos de prompts recomendados para tareas de codigo/documentos.
- Revisar encoding de docs y strings visibles.

### Evaluacion

- Definir una suite v0.1 pequena que se ejecute en CI local: seguridad, escritura, bash, loop, run logging, multiagente.
- Separar evals mock de evals live con Ollama.
- Anadir casos "documento -> archivo" y "PDF ejercicio -> carpeta scoped".
- Medir falsos positivos/negativos del multiagente con modelos pequenos.
- Mantener redteam basico para fenced tools, secretos, bash y workspace escapes.

## 6. Tests relevantes

| Archivo de test | Que cubre | Por que importa para v0.1 |
|---|---|---|
| `tests/test_cli_help.py`, `tests/test_cli_models.py`, `tests/test_cli_doctor.py`, `tests/test_cli_menu.py` | Ayuda, modelos, doctor y menu CLI. | Aseguran que el producto es arrancable y explicable desde terminal. |
| `tests/test_pipeline.py` | Preparacion de sesion, catalogo, budgets de output. | Une router/modelo/config con el arnes real. |
| `tests/test_harness_loop.py` | Loop ReAct, tool execution, nudges, cache, finalizacion, sesiones, contrato simple write+readback. | Es el nucleo del agente clasico. |
| `tests/test_harness_tools.py` | Lectura de archivos, PDFs, DOCX/XLSX, grep y roundtrip read/write/edit. | Soporta tareas de codigo/documentos de v0.1. |
| `tests/test_new_tools.py` | `todo_write`, `ask_user`, web, notebooks, git. | Cubre herramientas auxiliares y de evidencia. |
| `tests/test_write_preview.py`, `tests/test_write_file_intent_policy.py`, `tests/test_apply_patch.py` | Preview/diff, bloqueo de writes, apply_patch y escritura real. | Base de edicion segura y auditable. |
| `tests/test_workspace_security.py`, `tests/test_security_core.py` | Workspace confinement, escapes, `--yes`, auditoria. | Garantia principal de seguridad local. |
| `tests/test_secret_files_policy.py`, `tests/test_secret_files_v02.py` | Bloqueo de secretos y falsos positivos controlados. | Evita filtraciones obvias. |
| `tests/test_bash_safety.py`, `tests/test_bash_redirect.py`, `tests/test_bash_windows_vectors.py` | Blocklist bash, redireccion bash->tool, vectores Windows. | Reduce riesgo de comandos peligrosos y malos habitos de modelos. |
| `tests/test_security_engine.py`, `tests/test_security_engine_comparison.py`, `tests/test_security_profiles.py`, `tests/test_session_permissions.py` | Engines, perfiles, reglas allow/ask/deny, aprobaciones de sesion, auditoria. | Define el modelo de permisos de v0.1. |
| `tests/test_run_logger.py` | Carpetas de run, resumen, tool calls, tokens, `--no-log`. | Da trazabilidad verificable. |
| `tests/test_completion_verifier.py` | Verificador opcional y parseo conservador. | Importante para no confundir texto final con evidencia. |
| `tests/test_multiagent_intent.py` | Clasificacion de intent, scope constraints, dangerous ops, routing. | Evita fases incorrectas en multiagente. |
| `tests/test_multiagent_runner.py` | Allowlist por rol, prompts de subagente, interseccion skill+rol, progreso. | Cubre la disciplina de herramientas por fase. |
| `tests/test_multiagent_orchestrator.py` | Secuencia, prompts, reparacion, status final, trazas parent/multiagent. | Cubre el flujo multiagente completo. |
| `tests/test_multiagent_tooling.py` | Evidencia de tools por fase, role violations, validation contract, artifact validation, scope, git evidence. | Es la suite mas cercana a los incidentes observados. |
| `tests/test_multiagent_cli.py`, `tests/test_multiagent_repl.py` | Entrada CLI/REPL al orquestador multiagente. | Asegura que el modo opcional se activa correctamente. |
| `tests/test_evals.py`, `tests/harness_write_eval/` | Evals mock, checks esperados/prohibidos, escritura. | Base para regresion de producto. |
| `tests/redteam/test_redteam_findings.py` | Regresiones redteam puntuales. | Protege contra bypasses ya descubiertos. |
| `tests/test_mcp.py`, `tests/test_skills.py`, `tests/test_research_skills.py` | MCP y skills. | Extensibilidad util, pero con superficie de riesgo. |

## 7. Riesgos tecnicos

- Sobreprometer seguridad: CI2Lab controla herramientas y rutas, pero no aisla procesos con sandbox de OS.
- Falsos positivos del multiagente por validacion conservadora: runs correctos pueden acabar `validation_failed` si falta evidencia.
- Falsos negativos de validacion semantica: leer y compilar no garantiza que el ejercicio o cambio sea correcto.
- Heuristicas de intent/scope pueden activarse o no activarse con phrasing inesperado.
- Dependencia de Git para evidencia de scope puede fallar fuera de repos o en entornos con permisos raros.
- Modelos locales pequenos pueden emitir herramientas mal formateadas, pseudo-tools por bash o claims narrativos sin evidencia.
- MCP/web/skills aumentan la superficie de fuga de datos y deberian estar claramente gobernados por permisos.
- Encoding y mezcla ingles/espanol en docs/UI pueden afectar confianza y soporte.
- La suite de tests es amplia, pero v0.1 necesita un subset oficial rapido y repetible.
- Cambios recientes en multiagente aun son jovenes; conviene una estabilizacion antes de ampliar features.

## 8. Propuesta de siguiente paso

El siguiente cambio concreto deberia ser crear una suite de regresion v0.1 documentada y ejecutable, por ejemplo `docs/v0_1_regression.md` mas un comando recomendado que agrupe tests de CLI, seguridad, escritura, run logging y multiagente. Eso fija la linea base antes de tocar nuevas features y convierte este diagnostico en una puerta de salida verificable.
