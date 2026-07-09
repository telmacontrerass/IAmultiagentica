# Puntos de dolor — depender solo de ci2lab

Análisis de los puntos de dolor del proyecto **si dependiéramos únicamente de `ci2lab`**
y no de otras IAs cloud (ChatGPT, Gemini, Claude…). Este documento es
**autocontenido**: la evidencia relevante de [`PAPER_DIRECTION.md`](PAPER_DIRECTION.md)
y [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) está transcrita aquí (ver
el [Anexo de evidencia](#anexo--evidencia-citada) al final) para no tener que saltar
entre ficheros.

> **Resumen en una línea:** `ci2lab` es *local-first* (modelos open-source servidos
> por Ollama en tu propia máquina). Esa es su virtud —privacidad, coste cero por
> token, offline— y a la vez el origen de casi todos sus puntos de dolor. Depender
> **solo** de él significa aceptar el techo de un modelo pequeño en hardware de
> consumo, sin escotilla de escape a un modelo más fuerte.

---

## Marco del problema

Lo que realmente cabe en hardware de consumo son modelos de **1B–32B**. El catálogo
([`ci2lab/catalog/models.json`](ci2lab/catalog/models.json)) lista 87 modelos, pero los
grandes (`llama3.1-405b` → 226 GB VRAM, `qwen3-235b` → 131 GB) son inejecutables fuera
de un datacenter. La franja realista (4–24 GB VRAM) es justo la banda donde un modelo
es **cualitativamente inferior** a un frontier en razonamiento multi-paso, planificación
de horizonte largo, código complejo y matemáticas.

El propio [`PAPER_DIRECTION.md`](PAPER_DIRECTION.md) construye toda su tesis sobre
*"weak local models"* y sobre **mecanismos externos al modelo** para compensarlos — es un
reconocimiento explícito de que el modelo, por sí solo, no basta. Los puntos de dolor se
ordenan de la causa raíz hacia sus consecuencias.

---

## 1. Techo de capacidad del modelo (la causa raíz)

La calidad está limitada por lo que cabe en hardware de consumo. Los `benchmark_score`
del catálogo, además, están **escritos a mano, no medidos**, así que ni siquiera puedes
fiarte de la puntuación al elegir modelo:

> *"`benchmark_score` in `catalog/models.json` is a **hand-authored prior, not
> measured** — never cite it as a result."* — [`PAPER_DIRECTION.md`](PAPER_DIRECTION.md) §6

**Nota de procedencia (verificada contra la fuente).** Estos `benchmark_score` NO
provienen de una evaluación externa. Se confundían con el sistema de *hardware-fit* de
[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) (el proyecto de PewDiePie,
`services/hwfit/`), del que ci2lab tomó **solo el patrón** ("escanear hardware → puntuar
encaje → catálogo", sin copiar código —
[`references/EXTRACTION_LOG.md`](references/EXTRACTION_LOG.md)). Pero son dos cosas
distintas:

| | Odysseus (`hwfit`) | ci2lab (`benchmark_score`) |
|---|---|---|
| Qué puntúa | Encaje con tu hardware (cuantización, VRAM, velocidad) | Calidad del modelo por tarea (coding/reasoning/rag/edge) |
| Cómo se obtuvo | Calculado desde metadatos + descubrimiento HuggingFace | **Escrito a mano**, no medido |
| ¿Es de PewDiePie? | Sí, el patrón | No — es propio de ci2lab |

Verificado leyendo `services/hwfit/models.py` de Odysseus: *"No per-model benchmark
scores are present in this code"* — su hwfit calcula encaje-hardware e infiere el
`use_case` del nombre del modelo, pero **no almacena puntuaciones de calidad por tarea**.
Las de ci2lab son una invención propia sin validación empírica.

**Consecuencia de depender solo de esto:** tareas que un frontier resuelve de una pasada
aquí fallan, se degradan o requieren que el usuario las trocee manualmente.

## 2. El harness necesita "muletas" porque el modelo se atasca

Existe una batería de ~10 guardarraíles (detección de bucles, corte por racha de errores,
`retry_governor`, nudges en [`ci2lab/harness/query/loop.py`](ci2lab/harness/query/loop.py))
precisamente porque los modelos pequeños entran en bucle, alucinan llamadas a herramientas
y no cierran tareas. Es infraestructura para **contener** la debilidad del modelo, no para
añadir capacidad. El propio código advierte que el timing de nudges/rondas es frágil.

> Evidencia de [`KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md): *"Task-agnostic loop
> — the loop has no per-topic special cases; robustness comes from generic mechanisms
> (loop detection, error-streak cutoff, workspace-policy handling, edit follow-ups,
> `web_fetch`→`web_search` redirect, and a few recovery nudges)."*

## 3. No hay árbitro fuerte que verifique el trabajo

El punto de dolor **más específico de "solo ci2lab"**. La verificación depende de:

- Un **LLM-judge** que en la ruta por defecto es *el mismo modelo débil juzgándose a sí
  mismo* ([`ci2lab/harness/query/verifier.py`](ci2lab/harness/query/verifier.py), off por
  defecto) + heurística regex ([`ci2lab/harness/grounding_review/`](ci2lab/harness/grounding_review/)).
- El cierre determinista con evidencia solo existe en la ruta **opt-in `--multi-agent`**.

> *"Deterministic evidence-grounded closure — real but **`--multi-agent`/opt-in only**;
> default path uses LLM-judge (`verifier.py`, off by default) + regex heuristic."*
> — [`PAPER_DIRECTION.md`](PAPER_DIRECTION.md) §2

El paper cita el resultado de ICLR 2024: los LLM **no se autocorrigen de forma fiable sin
ayuda externa** (*"LLMs cannot reliably self-correct unaided — motivates model-external
mechanisms for weak models"*, §7). El "multiagente" de ci2lab es el mismo modelo pequeño
con distintos sombreros — no aporta una segunda opinión genuinamente más capaz. En un flujo
híbrido, ChatGPT/Gemini actúan como ese verificador externo más fuerte; aquí no hay ninguno.
Se suman dos fallos característicos: `tool_trace_failed` (resultado correcto pero
**improbable de demostrar**) y el **false-positive success** (afirma éxito sin evidencia).

## 4. Parsing de herramientas heterogéneo y frágil

> *"Heterogeneous parser — local models may print tool calls as plain text."*
> — [`KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md)

Los modelos no catalogados caen a `tool_mode: fenced`. El tool-calling nativo fiable —que
las APIs frontier dan resuelto— aquí es una fuente estructural de fallos, y cada fallo de
parseo quema una ronda del loop.

## 5. Contexto pequeño, compactación con pérdida y coste de herramientas

Muchos modelos ejecutables realmente rondan **8k–32k** de contexto. La compactación
resume/recorta con un **trim grosero (~4 caracteres/token)**, que pierde información:

> [`KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md): *"Compaction — old history is
> summarized or trimmed"*; *"Coarse trim — ~4 characters/token"*.

Frente a las ventanas de 200k–1M+ fiables de los frontier, trabajar sobre documentos largos
o bases de código grandes duele. Y se agrava: el *progressive disclosure* del Yard es **O(1)
solo para el Yard** — cada esquema de herramienta MCP se inyecta **en cada turno**:

> *"Tool churn without retraining — O(1) **only Yard**, not MCP (every MCP tool schema is
> injected every turn)."* — [`PAPER_DIRECTION.md`](PAPER_DIRECTION.md) §2 y §5

Cuantas más herramientas conectas, más ahogas al modelo débil.

## 6. Multimodalidad y conocimiento limitados

- **Multimodal:** hay pre-proceso de visión/PDF (`_prepare_turn_content` en
  [`ci2lab/harness/query/loop.py`](ci2lab/harness/query/loop.py)), pero depende de que el
  modelo local soporte visión — la mayoría de los pequeños son texto-only o con visión
  pobre; no hay audio.
- **Conocimiento y actualidad:** un modelo pequeño tiene menos conocimiento paramétrico,
  cutoff más antiguo y **más alucinación**. El único anclaje a la realidad es la
  herramienta `web_search`/`web_fetch` (DuckDuckGo vía `ddgs`), no una búsqueda integrada
  de calidad.
- **Idiomas:** los modelos pequeños rinden peor fuera del inglés; y localmente hay fricción
  añadida (UI web en español, agente en inglés):

> *"Web frontend still in Spanish — the agent system prompt, the terminal/CLI UI, and tool
> outputs are English, but the web UI page text is still Spanish."* y *"A few tool output
> strings still in Spanish."* — [`KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md)

## 7. Carga operativa, hardware y latencia

Cero-setup no existe aquí. No hay auto-pull, el usuario gestiona Ollama, VRAM y cuantización,
y sufre la latencia de inferencia en CPU/GPU de consumo:

> [`KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md): *"No auto-pull — `runtime/ensure.py`
> does not exist; the user must run `ollama pull`."* · *"Automatic runtime (`ollama pull` /
> ensure) — Not implemented."*

Frente al "abre la web y escribe" de ChatGPT/Gemini, la barrera de entrada y el
mantenimiento son reales y recurrentes.

## 8. Sin sandbox real: riesgo al ejecutar un agente propenso a errores

> [`KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md), sección *Security and sandbox*:
> *"No OS/container sandbox — confirmation + blocklist; no seccomp or isolated network"* ·
> *"Sensitive files — heuristic in `secret_files`; not a perfect classifier"* ·
> *"`bash` with `shell=True` — `--yes` does not skip the workspace blocklist."*
>
> [`PAPER_DIRECTION.md`](PAPER_DIRECTION.md) §4 (*Do NOT claim*): *"'Novel
> governance/security' — it is OpenCode re-implemented, no threat model"* · *"'Secret
> protection' — filename-only blocking, no value redaction."*

Un agente débil y propenso a equivocarse, con acceso real a filesystem y `bash`, protegido
solo por una lista negra por nombre de fichero, es un riesgo tangible. Los asistentes cloud
ejecutan herramientas en entornos gestionados y aislados.

## 9. Punto único de fallo: no hay fallback ni redundancia

Directamente ligado a la pregunta. **No hay enrutado multi-modelo por turno**:

> [`KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md), *Out of scope*: *"Per-turn
> multi-model routing — Not implemented"* · *"Vector memory across sessions — Not
> implemented"*.

Si el modelo local es malo en una tarea concreta, **no hay a quién escalar**. Un flujo
híbrido te deja saltar a un modelo más fuerte cuando el local se atasca; con solo ci2lab,
si el modelo local no puede, la tarea no se hace. Tampoco hay memoria entre sesiones que
compense con el tiempo.

## 10. Evidencia inmadura: ni siquiera puedes medir cuánto duele

El propio roadmap reconoce que el instrumento de medida todavía no está calibrado:

> [`PAPER_DIRECTION.md`](PAPER_DIRECTION.md) §6 (*Roadmap — P0 fixes*):
> 1. *"**Fix the telemetry bug.** The bench adapter reads `run.json`, but the single-agent
>    loop writes `run_summary.json`, so `rounds` / failure-attribution are silently dropped
>    for the **primary** condition (`ci2lab/bench/adapters/ci2lab_adapter.py`). Also map the
>    `"stuck"` status (absent from `_RUN_STATUS_MAP`)."*
> 2. *"**Run the live matrix once.** Nothing is committed end-to-end yet."*
> 3. *"**Add bootstrap CIs** to `summary.json` (`_aggregate` currently emits point estimates
>    only)."*
> 4. *"**Author harder tasks.** 12 fixtures won't carry a conference paper."*
> 5. *"Fix the stale orchestrator docstring (`orchestrator.py:1-6`)."*
>
> Caveats de integridad de datos: *"`benchmark_score` … a hand-authored prior, not
> measured."* · *"Runs are auditable but **not replayable** (no seed capture / no replay
> harness)."*

Depender solo de ci2lab hoy es volar con instrumentación parcial: no puedes cuantificar de
forma fiable cuándo va a fallar.

---

## Síntesis: inherentes vs. solucionables

- **Inherentes al enfoque local-first** (no se "arreglan" del todo, se mitigan): techo de
  capacidad (#1), necesidad de muletas (#2), ausencia de árbitro fuerte (#3), contexto
  pequeño (#5), multimodalidad/conocimiento (#6), latencia/hardware (#7). Son el precio
  estructural de no usar cloud.
- **Fixables con ingeniería** (deuda, no destino): parsing frágil (#4), sandbox (#8),
  fallback multi-modelo (#9), auto-pull/DX (#7 parcial), madurez de evidencia (#10),
  localización (#6 parcial), coste de esquemas MCP (#5 parcial).

**El más crítico si dependes solo de esto es el #9 combinado con el #3:** no solo el modelo
es más débil, sino que **no hay una inteligencia superior que verifique su trabajo ni a la
que escalar cuando falla**. Ahí es exactamente donde un ChatGPT/Gemini cierra el hueco en un
flujo híbrido.

---

## Puntos de dolor que PODEMOS solucionar o aliviar

Ordenados por relación impacto/esfuerzo. "Solucionable" = deuda de ingeniería que se puede
cerrar; "Aliviable" = mitigable aunque no eliminable del todo con modelos locales.

### Nivel A — Solucionables ya (bugs / features acotadas, alto impacto)

| # | Punto de dolor | Acción concreta | Dónde | Estado |
|---|----------------|-----------------|-------|--------|
| 10 | Telemetría rota en la condición primaria | Leer `run_summary.json` (no `run.json`) y mapear el estado `"stuck"` en `_RUN_STATUS_MAP` | [`ci2lab/bench/adapters/ci2lab_adapter.py`](ci2lab/bench/adapters/ci2lab_adapter.py) | ✅ Ya estaba corregido (audit obsoleto): `_read_run_json` hace el fallback y `_RUN_STATUS_MAP` ya mapea `"stuck"` |
| 10 | Sin intervalos de confianza | Añadir bootstrap CIs a `_aggregate`/`summary.json` | [`ci2lab/bench/metrics.py`](ci2lab/bench/metrics.py), [`ci2lab/bench/runner.py`](ci2lab/bench/runner.py) | ✅ Hecho: `bootstrap_ci()` + `pass_at_1_ci`/`pass_at_k_ci` (95%, reproducibles) |
| 10 | Docstring del orquestador obsoleto/falso | Corregir `orchestrator.py:1-6` | [`ci2lab/harness/multiagent/orchestrator.py`](ci2lab/harness/multiagent/orchestrator.py) | ✅ Hecho: docstring reescrito (multiagente es ruta opt-in, no "sin cablear") |
| 7 | Typo/modelo ausente → crash críptico | Check con error claro + "did you mean" (auto-pull descartado) | `ci2lab/runtime/`, `ci2lab/cli/commands/agent.py` | ⏳ Pendiente (intento revertido; requiere arreglar antes el bug de parser `--model` antes del subcomando) |
| 1 | `benchmark_score` sin respaldo empírico | Correr la matriz live una vez y sustituir priores por medidas; mientras tanto, marcarlos como no-fiables en la UI de recomendación | `ci2lab/catalog/models.json`, `ci2lab/router/recommend.py` | ⏳ Pendiente (los benchmarks los trabaja un compañero de equipo) |
| 6 | Cadenas de salida aún en español | `write_preview` "archivos"→"files" (grep ya era inglés); `quiz.py` y palabras-gatillo se dejan en español a propósito | [`ci2lab/harness/tools/write_preview.py`](ci2lab/harness/tools/write_preview.py) | ✅ Hecho |

### Nivel B — Solucionables con trabajo medio (cierran huecos estructurales)

| # | Punto de dolor | Acción concreta |
|---|----------------|-----------------|
| 9 | **Punto único de fallo** — sin fallback | Implementar enrutado multi-modelo por turno: escalar a un modelo local mayor (o a un backend OpenAI-compatible/cloud opcional) cuando se dispare la detección de bucle o el corte por racha de errores. Aprovecha que el backend ya es enchufable. |
| 3 | Verificación débil | Hacer el cierre determinista con evidencia la ruta **por defecto** (no solo `--multi-agent`); permitir configurar un "modelo juez" distinto (y opcionalmente más fuerte) del "modelo trabajador". |
| 5 | Esquemas MCP inyectados cada turno | Extender el *progressive disclosure* O(1) del Yard (`list/describe/run`) a las herramientas MCP para no quemar contexto. |
| 4 | Parsing frágil | Validación estricta de argumentos de herramientas (extracción pendiente citada de OpenCode) + más formatos de tool-call reconocidos en el parser. |
| 10 | Runs no replayables | Capturar seed + construir un replay harness para que los resultados sean reproducibles. |
| 10 | Cobertura de eval escasa | Ampliar de 12 a un set de fixtures multi-paso / recuperación / seguridad más grande. |

### Nivel C — Aliviables (mitigación, no cura; el techo local sigue)

| # | Punto de dolor | Mitigación |
|---|----------------|-----------|
| 8 | Sin sandbox de OS | Añadir un sandbox opcional (contenedor/seccomp) + **redacción de valores** de secretos (no solo bloqueo por nombre de fichero). Reduce el riesgo, no elimina que el agente se equivoque. |
| 5 | Contexto pequeño | Mejorar la compactación (resumen semántico en vez de trim a ~4 chars/token) y priorizar contexto relevante; sigue sin igualar a un frontier de 1M. |
| 6 | Multimodalidad | Rutar tareas de visión a modelos locales con visión cuando existan; degradar con aviso claro cuando el modelo elegido no soporte la modalidad. |
| 2 | El modelo se atasca | Seguir endureciendo los guardarraíles genéricos (con cuidado por el timing frágil del loop); no elimina la causa (modelo débil). |
| 9 | Sin memoria entre sesiones | Añadir memoria vectorial persistente para acumular contexto de proyecto entre sesiones. |
| 7 | Latencia | Cuantización adecuada, warmup del modelo, streaming (ya existe); acotado por el hardware del usuario. |

### Inherentes — no solucionables sin cloud (documentar, no prometer)

- **#1 techo de capacidad** y **#6 conocimiento/actualidad**: un modelo de 1B–32B no
  igualará a un frontier en razonamiento, código complejo o conocimiento. La honestidad
  del scope (como ya hace `PAPER_DIRECTION.md`) es la mejor "solución": vender ci2lab como
  instrumento de *medición* de fiabilidad local, no como sustituto de un frontier.
- El **#9 en su forma pura** (tener a mano una inteligencia superior) solo se cierra con un
  backend cloud opcional — que rompería la promesa *100% local*. Es una decisión de
  producto, no un bug.

---

## Anexo — evidencia citada

Transcripción de las secciones referenciadas, para que este documento sea autocontenido.

### A. De `PAPER_DIRECTION.md`

**§1 — Lo que el estado del arte NO hace bien (y ci2lab podría medir):**
- Aislar cuánta fiabilidad del agente local viene del **harness** vs. el **modelo** — todo
  paper SOTA los confunde.
- Medir agentes más allá del éxito de tarea: **provenance, evidencia, false-positive
  success, atribución de fallo, coste-por-éxito**.
- Tratar la **fiabilidad operativa** como objeto medible, no como detalle de ingeniería.

**§2 — Scorecard (filas relevantes):**

| Contribución | Qué hay construido | Veredicto honesto |
|---|---|---|
| Cierre determinista con evidencia | Real pero **`--multi-agent`/opt-in**; la ruta por defecto usa LLM-judge (`verifier.py`, off) + heurística regex (`grounding_review/`) | Real si se acota con honestidad |
| Tool churn sin reentrenar | O(1) **solo Yard**, no MCP (cada esquema MCP se inyecta cada turno) | Buena sección de sistemas; aún no afilada |
| Gobernanza/permisos | `security/` = reimplementación de OpenCode/Claude-Code; sin modelo de amenazas, sin redacción de valores de secretos, sin sandbox de OS, sin eval adversarial | **Sobrevendido — derivativo** |

**§4 — Lo que NO se debe reclamar:**
- *"Novel governance/security"* — es OpenCode reimplementado, sin modelo de amenazas.
- *"Secret protection"* — bloqueo solo por nombre de fichero, sin redacción de valores.
- *"General artifact validation"* — no existe verificación basada en compilar/testear.
- Cierre determinista en la ruta por defecto — el default es LLM-judge + heurística.

**§6 — P0 fixes y caveats de integridad de datos:** (transcritos en el punto #10 arriba).

**§7 — Literatura de auto-corrección (motivación):**
- AgentBench / "Where LLM Agents Fail" — documentan bucles / agotamiento de presupuesto.
- Reflexion, Self-Refine, ReflexGrad — auto-corrección basada en reflexión.
- Resultado ICLR 2024: los LLM **no se autocorrigen de forma fiable sin ayuda** — motiva
  mecanismos **externos al modelo** para modelos débiles.

### B. De `docs/KNOWN_LIMITATIONS.md`

**Pipeline ↔ router:**
- El router no auto-selecciona modelo en chat (`recommend` sugiere; el usuario elige con
  `--model`).
- Tags no catalogados → `tool_mode: fenced` por defecto.
- **No auto-pull** — `runtime/ensure.py` no existe; el usuario ejecuta `ollama pull`.
- `ci2lab agent --session` guarda pero **no carga** mensajes previos (sí lo hacen `chat
  --session` y la UI).

**Out of scope:** runtime automático (no implementado) · git snapshot/rollback/auto-commit
(no) · **per-turn multi-model routing (no)** · benchmark live por modelo (solo scores
estáticos) · **memoria vectorial entre sesiones (no)** · hooks estilo Claude-Code (solo
ciclo básico `before_tool`/`after_tool`/`after_final_answer`).

**Localización:** frontend web aún en español; algunas cadenas de salida de herramientas aún
en español (el agente y el CLI son en inglés).

**Seguridad y sandbox:** sin sandbox de OS/contenedor (confirmación + blocklist, sin seccomp
ni red aislada) · ficheros sensibles por heurística (`secret_files`, clasificador
imperfecto) · `bash` con `shell=True` (`--yes` no salta la blocklist del workspace).

**Operación del harness:** parser heterogéneo (los modelos locales pueden imprimir las
llamadas como texto plano) · loop task-agnostic (robustez por mecanismos genéricos) ·
compactación (historial viejo resumido o recortado) · **trim grosero ~4 caracteres/token**.

### C. Procedencia de `benchmark_score` (verificada contra el repo de Odysseus)

- `references/EXTRACTION_LOG.md`: de Odysseus se tomó *"the idea of 'hardware scan + fit
  scoring + model catalog' (from its README + `services/hwfit/`); **no code copied**"*.
- `docs/HARDWARE_ROUTER_HANDOFF.md` §6.1 y §13: la fuente de `models.json` es la **"project
  model table"** interna, no Odysseus.
- Repo de Odysseus (`services/hwfit/models.py`, verificado): carga de
  `data/hf_models.json` + `data/mlx_community_models.json` con campos `name`,
  `quantization`, `parameter_count`, `is_moe`, `use_case` (inferido del nombre)… →
  **"No per-model benchmark scores are present in this code."** Su scoring es
  hardware-fit (bytes/parámetro, velocidad, penalización de cuantización), no calidad por
  tarea.
- Conclusión: los `benchmark_score` de ci2lab son **priores escritos a mano dentro de
  ci2lab**, no una evaluación de Odysseus.
