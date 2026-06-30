# Stashed changes concepts

Creado: 2026-06-30. Basado en inspección de lectura pura (sin `stash apply` ni `stash pop`).

---

## Current safe baseline

`main` está limpio y alineado con `origin/main`. Los 4 stashes siguen intactos.
Ningún stash fue aplicado para generar este informe.
Todos los comandos usados fueron de solo lectura (`git stash show`, `git stash show -p`).

---

## Stash inventory

| Stash | Origen | Archivos principales | Área | Riesgo | Estado vs main |
|---|---|---|---|---|---|
| `stash@{0}` | experiment/multiagent-validation-evidence-approvals | orchestrator.py, tests/test_multiagent_tooling.py | Multiagent — scope validation | MEDIO | Nada en main; independiente |
| `stash@{1}` | fix/multiagent-validation-evidence | orchestrator.py, state.py, loop.py, json_tools.py, 4 tests | Multiagent + loop + parsing | ALTO | Parcialmente en main (solo `menu`); resto pendiente |
| `stash@{2}` | main (wip before safe pull) | parser.py, loop.py, fenced_tools.md, 2 tests | Loop — web_search nudge | —— | **OBSOLETO** — todo ya está en main HEAD |
| `stash@{3}` | main (GitHub Desktop) | security/engine.py + 15 archivos más | Security — renombrado `policy_v1` | MEDIO-ALTO | Nada en main; bien estructurado pero toca muchos archivos |

---

## Extracted concepts

### Concept A — Nested JSON tool call parsing

- **Stash:** `stash@{1}`
- **Archivo:** `ci2lab/harness/parsing_parts/json_tools.py`
- **Descripción:** `_calls_from_json_value()` — función recursiva que extrae tool calls de JSON anidado estilo Llama3 (`{"tool_calls": [{"name": ..., "parameters": {...}}]}`). El código actual solo maneja objetos planos; los modelos Llama estructuran las llamadas un nivel más profundo.
- **Valor esperado:** Fix para modelos Llama3/Llama3.1 que no son reconocidos como tool calls cuando el JSON está anidado.
- **Ya en main:** NO.
- **Riesgo:** BAJO — cambio contenido en un solo archivo, solo parsing, sin side effects en lógica de negocio.
- **Plan de integración:** PR de 1 archivo (`json_tools.py`) + 1 test (`test_parse_llama_nested_tool_calls_with_parameters`). Sin tocar loop ni orchestrator.
- **Tests mínimos:** `test_harness_parsing.py` completo (ya tiene ~170 tests de parsing).

---

### Concept B — Fenced tool result reinjection

- **Stash:** `stash@{1}`
- **Archivo:** `ci2lab/harness/query/loop.py`
- **Descripción:** `_append_fenced_tool_results()` — reinyecta los resultados de tools de escritura (`write_file`, `edit_file`, etc.) como mensaje de usuario en el historial, para que el modelo fenced vea en la siguiente ronda qué devolvió el tool. Sin esto, el modelo en modo fenced no sabe si su escritura tuvo éxito.
- **Valor esperado:** Elimina el patrón donde un modelo fenced repite la misma llamada a `write_file` porque nunca recibió confirmación del resultado.
- **Ya en main:** NO.
- **Riesgo:** BAJO-MEDIO — solo afecta flujos con `tool_mode="fenced"`. Necesita la guardia `not llm_response.tool_calls` para no duplicar en modo nativo.
- **Plan de integración:** PR de 1 archivo (`loop.py`) + 1 test (`test_fenced_mode_reinjects_tool_results_as_text_for_next_round`). Separado del contrato write/readback (Concept C).
- **Tests mínimos:** `test_harness_loop.py` completo; verificar tests de modo nativo no se rompen.

---

### Concept C — Contract early exit in loop (write + readback)

- **Stash:** `stash@{1}`
- **Archivo:** `ci2lab/harness/query/loop.py`
- **Descripción:** `_contract_expected_from_prompt()` + `_contract_completed_by_results()` — el loop de `run_agent` detecta cuándo el prompt pide crear un archivo con contenido exacto y el agente ya ejecutó write_file + read_file con éxito. En ese momento, el loop sintetiza la respuesta final y sale sin esperar más rondas.
- **Valor esperado:** Evita que el agente quede "atascado" repitiendo herramientas o esperando una ronda de "texto final" que nunca llega en modelos fenced.
- **Ya en main:** NO.
- **Riesgo:** MEDIO — modifica el flujo de control del loop principal. Depende de Concept B (reinjection) para funcionar bien en secuencia. Las regex de detección de contrato deben ser estrechas para no activarse en tareas que no son de creación de archivo exacto.
- **Plan de integración:** PR de 1 archivo (`loop.py`), después de fusionar Concept B. Incluir los 2 tests nuevos de loop.
- **Tests mínimos:** `test_harness_loop.py` completo; los 2 tests nuevos del stash.

---

### Concept D — classify_file_creation_contract (post-validator layer)

- **Stash:** `stash@{1}`
- **Archivos:** `ci2lab/harness/multiagent/orchestrator.py`, `ci2lab/harness/multiagent/state.py`
- **Descripción:** `classify_file_creation_contract()` — capa adicional sobre el validador que verifica objetivamente (filesystem + tool trace) si una tarea de creación de archivo fue completada. Distingue cuatro casos:
  - `completed` — archivo existe, contenido correcto, tools evidenciados
  - `validation_failed` — archivo no existe, o contenido incorrecto, o el validador reportó fallo
  - `insufficient_evidence` — archivo existe pero no hay tool calls de write/readback en el historial
  - `tool_trace_failed` — archivo existe y tools ejecutados, pero el coder no declaró explícitamente el tool usado en su respuesta narrativa
- **Valor esperado:** Elimina falsos positivos: el validador puede decir "PASS" aunque el archivo no exista. Esta capa lo captura de forma determinista.
- **Ya en main:** NO. `state.contract_validation` tampoco existe.
- **Riesgo:** MEDIO — requiere nuevo campo en `MultiAgentRun`, cambios en `_trace_payload`, `final_run_status`, `synthesize_final_answer` y `run_multi_agent`. Son 2 archivos pero muy centrales.
- **Plan de integración:** PR con `state.py` (nuevo campo) + `orchestrator.py` (función + hooks de integración) + tests `test_multiagent_orchestrator.py`. Separar de Concept E.
- **Tests mínimos:** `test_multiagent_orchestrator.py` y `test_multiagent_tooling.py`.

---

### Concept E — tool_trace_failed classification in trace + synthesize

- **Stash:** `stash@{1}`
- **Archivo:** `ci2lab/harness/multiagent/orchestrator.py`
- **Descripción:** Extiende `_trace_payload` con campos `failure_classification` y `contract_validation`, y `synthesize_final_answer` con un bloque para `status == "tool_trace_failed"` que explica al usuario que el archivo fue creado pero el coder no declaró el tool.
- **Valor esperado:** Mejor observabilidad en el trace JSON y mejor explicación al usuario cuando el fallo es de trazabilidad, no funcional.
- **Ya en main:** NO.
- **Riesgo:** BAJO — additive, no rompe ningún comportamiento existente. Lógicamente acoplado a Concept D.
- **Plan de integración:** Puede ir en el mismo PR que Concept D o separado como PR de solo trace/synthesize.
- **Tests mínimos:** Tests del multiagent trace format.

---

### Concept F — Contract instructions in implementation prompt

- **Stash:** `stash@{1}`
- **Archivo:** `ci2lab/harness/multiagent/orchestrator.py`
- **Descripción:** `_build_implementation_prompt` y `_build_repair_prompt` detectan si el prompt pide un contrato de archivo exacto y, si es así, inyectan instrucciones explícitas: "tu primera respuesta debe ser exactamente un bloque fenced `write_file`, después `read_file`, sin prosa previa".
- **Valor esperado:** Reduce drásticamente la tasa de fallos en modelos fenced para tareas de file creation contract al guiar el patrón de acción esperado.
- **Ya en main:** NO.
- **Riesgo:** MEDIO-BAJO — solo modifica el texto del prompt de implementación; no toca lógica de flujo. Pero puede afectar otros tests de snapshot de prompt.
- **Plan de integración:** Puede ir en el mismo PR que Concept D, o solo.
- **Tests mínimos:** `test_multiagent_tooling.py`; verificar que tests existentes de prompt no son snapshots que fallen.

---

### Concept G — Folder scope inference (allowed_write_roots)

- **Stash:** `stash@{0}`
- **Archivo:** `ci2lab/harness/multiagent/orchestrator.py`
- **Descripción:** `_infer_allowed_write_roots()` detecta prompts del tipo "crea una carpeta llamada `exercise_1` y trabaja dentro de ella" e infiere que las escrituras deben estar bajo ese root. `_scope_violation_paths()` detecta si el coder escribió fuera del root permitido. `allowed_write_roots` se añade a `ValidationContract`.
- **Valor esperado:** Detecta cuando el agente escribe fuera del folder scope prometido — falso negativo que el validador habitual no captura.
- **Ya en main:** NO.
- **Riesgo:** MEDIO — nuevo campo en `ValidationContract`, nuevas regex, integración en `build_validation_contract` y `_deterministic_validation_result`. Las regex de inferencia son heurísticas y pueden tener falsos positivos.
- **Plan de integración:** PR independiente de stash@{0}: solo `orchestrator.py` + 4 tests de folder scope. Mejor hacerlo después de Concept D (clasificación de contrato).
- **Tests mínimos:** Los 4 tests del stash: `test_folder_scope_allows_writes_inside_inferred_folder`, `test_no_folder_scope_inference_does_not_block_extra_paths`, `test_do_not_modify_other_file_restricts_to_expected_path`, `test_folder_scope_violation_fails_validation`.

---

### Concept H — policy_v1 security engine rename

- **Stash:** `stash@{3}`
- **Archivos:** `ci2lab/security/engine.py` + 14 archivos más (cli.py, types.py, security_profiles.py, audit.py, comparison.py, approval_prompt.py, gate_check.py, opencode_permissions.py, session_permissions.py, permissions_dashboard.py, evals/runner.py, README.md, docs/, scripts/)
- **Descripción:** Renombra `claude_experimental` a `policy_v1` como motor seguro con guards duros. Lo convierte en el default (`DEFAULT_SECURITY_ENGINE = "policy_v1"`). Añade aliases de retrocompat con deprecation warning (`claude_experimental` → `policy_v1`). Añade `is_policy_v1_engine()`, `CLI_SECURITY_ENGINE_CHOICES`, `CANONICAL_SECURITY_ENGINES`. Añade `git_status`/`git_diff` a `_READ_TOOLS` en opencode_permissions.
- **Valor esperado:** Naming estable para el motor recomendado; elimina la confusión de que "experimental" sea el motor seguro recomendado. Retrocompat limpia.
- **Ya en main:** NO.
- **Riesgo:** MEDIO-ALTO — toca muchos archivos y el motor por defecto cambia. Bien estructurado con aliases retrocompat. Requiere actualizar todos los tests que esperan `"ci2lab"` como default. Puede romper configs de usuario existentes si no hay migración.
- **Plan de integración:** PR dedicado, solo seguridad. Verificar todos los tests de security antes y después. Coordinar con docs.
- **Tests mínimos:** `test_security_engine.py`, `test_policy_v1_default.py`, `test_claude_experimental.py`, `test_write_preview.py`.

---

### Concept I — stash@{2} (OBSOLETO)

- **Stash:** `stash@{2}`
- **Descripción:** web_search nudge en loop.py, live_fact_lookup skill, fenced_tools.md actualizado, tests.
- **Ya en main:** TODO. Web_search nudge, skill builtin, tests y fenced_tools.md ya están en main HEAD.
- **Acción:** No hacer nada. Este stash puede descartarse en algún momento.

---

## Recommended integration order

Del más seguro al más complejo. Cada PR debe estar verde (lint + mypy + pytest) antes de seguir.

1. **PR-1: Nested JSON parsing** (`json_tools.py` + 1 test)
   - Solo parsing, sin side effects. Archivos: `json_tools.py`, `test_harness_parsing.py`.
   - Prerequisito: ninguno.

2. **PR-2: Fenced tool result reinjection** (`loop.py` + 1 test)
   - Guardia `not llm_response.tool_calls` para no duplicar en nativo.
   - Archivos: `loop.py`, `test_harness_loop.py`.
   - Prerequisito: PR-1.

3. **PR-3: state.contract_validation + trace fields**
   - Solo el campo nuevo en `state.py` + los campos en `_trace_payload`.
   - Archivos: `state.py`, `orchestrator.py` (solo trace/synthesize).
   - Prerequisito: ninguno (puede ir en paralelo con PR-2).

4. **PR-4: classify_file_creation_contract + contract instructions**
   - `orchestrator.py`: classify + integración en run_multi_agent + prompts.
   - Archivos: `orchestrator.py`.
   - Prerequisito: PR-3.

5. **PR-5: Contract early exit in loop**
   - `_contract_expected_from_prompt` + `_contract_completed_by_results` en loop.
   - Archivos: `loop.py`, `test_harness_loop.py` (2 tests nuevos).
   - Prerequisito: PR-2, PR-4.

6. **PR-6: Folder scope inference**
   - `allowed_write_roots` en ValidationContract + `_infer_allowed_write_roots` + `_scope_violation_paths`.
   - Archivos: `orchestrator.py`, `test_multiagent_tooling.py`.
   - Prerequisito: PR-4.

7. **PR-7: policy_v1 security engine rename**
   - Gran cambio, bien estructurado. 15+ archivos, default engine cambia.
   - Prerequisito: ninguno técnico, pero conviene que el resto esté estable primero.

---

## Do not integrate as-is

### stash@{1} completo de golpe

El stash@{1} mezcla 5 conceptos independientes en 8 archivos. Cuando se aplicó entero:
- `_append_fenced_tool_results` hizo crecer el historial hasta activar el resumidor de contexto en tests existentes, rompiendo tests que no tienen nada que ver con fenced mode.
- El bloque de contrato en loop.py quedó duplicado (dos `if contract_expected is not None:`) por un merge parcial con un bloque que usaba `_contract_completed_by_results` (función eliminada en HEAD).
- El validador determinístico interaccionó con `_enforce_change_scope_evidence` de forma no prevista en tests con `tmp_path` (no git repo).
- Los tests del contrato e2e requirieron 8 archivos modificados adicionales para estabilizarse.

**Regla:** Cada concepto listado arriba debe aplicarse en su propio PR, con tests en verde antes de fusionar el siguiente.

### stash@{3} completo de golpe

20 archivos tocados. Cambia el motor de seguridad por defecto. Si los tests existentes esperan `"ci2lab"` como default, todos fallan. Requiere auditoría de cada test de seguridad antes de aplicar.

### stash@{0} completo de golpe

La función `_infer_allowed_write_roots` usa regex heurísticas. Combinada con los cambios ya en orchestrator.py, puede activar scope enforcement en tareas que no son de folder scope (falsos positivos). Debe probarse de forma aislada con sus 4 tests dedicados.

### stash@{2}: ya está en main

No aplicar. Todo su contenido (web_search nudge, live_fact_lookup skill, tests) ya está en main HEAD. Aplicarlo generaría conflictos.

---

## Next Codex task proposal

**PR-1: Nested JSON tool call parsing (Llama-style)**

Tarea concreta:
1. En `ci2lab/harness/parsing_parts/json_tools.py`, añadir la función `_calls_from_json_value(value)` tal como aparece en `stash@{1}` (extraer de `git stash show -p "stash@{1}"`).
2. Actualizar las dos llamadas en `parse_json_tool_objects` que usan `json_object_to_call(obj)` para que llamen a `_calls_from_json_value(obj)` en su lugar.
3. Añadir el test `test_parse_llama_nested_tool_calls_with_parameters` a `tests/test_harness_parsing.py`.
4. Verificar: `python -m ruff check ci2lab tests`, `python -m mypy ci2lab`, `python -m pytest tests/test_harness_parsing.py -q`.

Archivos afectados: 2 (`json_tools.py`, `test_harness_parsing.py`).
Sin dependencias con otros cambios. Sin riesgo de romper tests existentes.
