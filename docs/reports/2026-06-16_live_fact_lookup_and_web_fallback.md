Informe de trabajo — live_fact_lookup, búsqueda web y fallback ante 403
======================================================================

Fecha: 2026-06-16

Estado inicial
--------------

- El arnés ya disponía de herramientas `web_search` y `web_fetch`, pero la ayuda de CLI y la guía de herramientas fenced no las explicaban bien.
- Las skills de investigación (`research_web_doc_review`, `research_web_vs_repo`) existían como builtin, pero no había una skill explícita para lookup factual/live sencillo.
- El bucle de agente (`run_agent`) no daba un empujón claro hacia `web_search` cuando el modelo respondía “no tengo acceso a internet”.
- No había documentación específica sobre el comportamiento esperado ante errores HTTP (incluyendo `403`) de `web_fetch`.

Trabajo realizado
-----------------

- Se ha incorporado una skill builtin `live_fact_lookup` pensada para consultas factuales/live simples.
- Se ha alineado la ayuda de CLI y la documentación de herramientas fenced para incluir `web_search` como primera parada en búsquedas live sin URL.
- Se ha añadido un nudge en el bucle del agente para que, cuando el modelo diga que no tiene acceso a internet y las tools lo permiten, se le recuerde explícitamente que puede usar `web_search` y luego `web_fetch`.
- Se ha añadido un nudge específico cuando `web_fetch` falla con errores HTTP típicos (incluyendo `403`), redirigiendo al modelo hacia `web_search` en lugar de repetir fetches o inventar URLs.
- Se han ajustado/añadido tests de harness para cubrir la nueva lógica, incluyendo el caso de empuje a `web_search` y el flujo docx→pdf en Windows.

Cambios técnicos
----------------

### CLI y documentación de herramientas

- `ci2lab/cli/parser.py`: la ayuda global ahora lista explícitamente `web_search` junto a `web_fetch` y añade una frase guía:
  - Si el usuario pide información live sin URL, se debe usar primero `web_search` y luego `web_fetch` para leer fuentes concretas.
- `ci2lab/harness/prompts/fenced_tools.md`:
  - Se ha documentado `web_search` con un ejemplo de bloque fenced para búsquedas live.
  - Se ha actualizado la lista de herramientas disponibles para incluir `web_search` junto a `web_fetch`.

### Bucle del agente y nudges web

En `ci2lab/harness/query/loop.py`:

- Se ha añadido `_NO_INTERNET_RE`, un regex que detecta mensajes del modelo del estilo “no tengo acceso a internet / no puedo buscar en tiempo real”.
- Durante la preparación de cada ronda:
  - Se calcula `web_search_available` comprobando si `web_search` está entre las herramientas permitidas para el modelo actual.
- En la fase de finalización de respuesta:
  - Si el modelo devuelve una respuesta final sin tool calls, `web_search` está disponible, aún no se ha enviado un nudge y el texto coincide con `_NO_INTERNET_RE`, se inserta un mensaje de sistema al estilo:
    - “You can use `web_search` for live info without a URL, then `web_fetch` for selected sources.”
  - Este nudge se envía solo una vez por ejecución para evitar bucles.
- En la fase de ejecución de herramientas:
  - Se usa la función `web_fetch_failed_nudge(results)` para detectar errores HTTP de `web_fetch` (incluyendo `403`) y se añade una instrucción de usuario que indica explícitamente:
    - que el URL probable es incorrecto o está bloqueado;
    - que no se deben adivinar nuevos URLs;
    - que hay que volver a `web_search` con una query textual y, a partir de ahí, usar `web_fetch` sobre resultados concretos.

Esto complementa la lógica general de detección de bucles de herramienta (`stuck_rounds`) que, tras repeticiones, fuerza una instrucción al modelo del estilo “Deja de repetir la misma herramienta… Responde ahora a la petición original usando los resultados de herramientas ya disponibles”.

### Skill builtin `live_fact_lookup`

- Se ha añadido `ci2lab/harness/skills/builtin/live_fact_lookup/SKILL.md` con:
  - `allowed_tools: web_search web_fetch`.
  - Un workflow obligatorio:
    1. Interpretar la pregunta factual/live.
    2. Si no hay URL, llamar a `web_search` con una query específica.
    3. Elegir una o dos fuentes fiables de los resultados.
    4. Llamar a `web_fetch` al menos una vez antes de afirmar hechos.
    5. Responder solo con información derivada de `web_search`/`web_fetch`.
  - Restricciones duras:
    - No inventar scores/fechas/resultados/versions no presentes en los snippets.
    - No usar herramientas distintas de `web_search` y `web_fetch` dentro de este workflow.
  - Formato de respuesta:
    - Texto plano (no JSON) salvo que el usuario pida explícitamente JSON.
    - Siempre incluir una línea `Fuente: ...`.
    - Permitir una línea de `Advertencia:` para matizar cuando la fuente es débil o ambigua.
  - Sección “When search or fetch fails” que ya apunta a:
    - No adivinar cuando no hay resultados útiles.
    - Probar otra fuente cuando `web_fetch` falla.
    - Explicar que no se ha podido verificar si nada funciona.

### Tests de harness

- `tests/test_skills.py`:
  - `test_builtin_research_skills_available` ahora verifica que `live_fact_lookup` está disponible como skill builtin.
  - `test_live_fact_lookup_skill_contract` asegura que:
    - `allowed_tools` se limita a `web_search` y `web_fetch`.
    - El prompt generado menciona explícitamente:
      - uso combinado de `web_search` + `web_fetch`;
      - respuesta en texto plano;
      - la línea `Fuente:` en el formato de salida;
      - la prohibición de inventar datos que no estén en `search/fetch`.
- `tests/test_harness_loop.py`:
  - `test_run_agent_prints_model_text_before_tool_execution` cubre que el texto del modelo se imprime antes de ejecutar tools.
  - `test_run_agent_nudges_web_search_once_after_no_internet_reply` valida que:
    - un primer turno con “No tengo acceso a internet en tiempo real” sin tools dispara un único nudge hacia `web_search`;
    - el segundo turno del modelo ve ese nudge y se espera que mencione que usará `web_search`.
  - `test_run_agent_forces_docx_conversion_after_repeated_discovery` se ha ajustado para ser portable en Windows:
    - En lugar de simular `bash` con `ls Prueba`, ahora se usa la tool `ls` con `{"path": "Prueba"}`.
    - Esto permite que el arnés detecte el `.docx` y fuerce `docx_to_pdf` incluso en entornos donde `ls` como comando de shell no existe.

Pruebas manuales realizadas
---------------------------

### `/live_fact_lookup resultado de España contra Cabo Verde`

- Ejecución vía slash skill:
  - El agente ha usado `web_search` con una query razonable sobre el partido España–Cabo Verde.
  - La UX ha sido buena: respuesta rápida, sin desvíos a `ask_user`, `tree`, `ls` ni `mcp_call` inventados.
- Incidencia observada:
  - La skill exige explícitamente llamar a `web_fetch` sobre al menos una fuente antes de afirmar hechos.
  - En la ejecución observada, el agente solo utilizó `web_search` y respondió directamente con el resultado del snippet de búsqueda, por lo que violó el contrato de la skill.

### Búsqueda natural sin slash: “busca el resultado entre España y Cabo Verde”

- Flujo observado (no deseado):
  - `web_search` inicial.
  - `web_fetch` a un resultado de YouTube.
  - `ask_user` innecesario pese a tener ya contexto suficiente.
  - Mala finalización y nuevo intento de búsqueda.
  - `web_fetch` a una página de predicciones, no de resultado real.
  - `mcp_call` inventado con nombre genérico `MCP_SERVER_NAME`.
  - Deriva posterior a filesystem: `tree` / `ls`, totalmente fuera de foco para una tarea factual/web.
- Conclusión:
  - El agente tiende a mezclar herramientas irrelevantes (filesystem, MCP inventados) cuando no se le acota la tarea web factual.
  - La nueva skill y los nudges de `web_search` van en la línea de acotar este espacio, pero aún falta implementar lógica de fallback más estricta para estos casos naturales sin slash.

### Consulta de precio de Bitcoin (Coinbase)

- Se probó una consulta de precio actual de Bitcoin, usando como una de las fuentes:
  - `https://www.coinbase.com/en-es/converter/btc/usd`
- Resultado:
  - `web_fetch` devolvió `HTTP 403`.
  - Este 403 es razonable: es esperable que sitios como Coinbase bloqueen tráfico automatizado, por lo que no se debe interpretar automáticamente como bug del fetcher.
  - El problema real es cómo responde el agente ante esta situación.
- Comportamiento observado (no deseado en general):
  - Tendencia a repetir búsquedas o fetches similares.
  - Posible invención de herramientas MCP o derivaciones a filesystem.
  - Falta de cierre limpio cuando se acumulan errores de fetch.

Pruebas automatizadas realizadas
--------------------------------

- Ejecución focalizada:
  - `pytest tests/test_skills.py tests/test_harness_loop.py -q`
    - Resultado: todos los tests relevantes pasan, incluyendo los nuevos sobre `live_fact_lookup` y el nudge a `web_search`.
- Suite completa:
  - `pytest tests/ -q`
    - Resultado: 669 tests pasados, 10 saltados en el entorno actual.
    - No se han observado fallos nuevos tras integrar las novedades de multiagente remoto y las modificaciones locales en el bucle del agente.

Resultado de `/live_fact_lookup resultado de España contra Cabo Verde`
----------------------------------------------------------------------

- UX:
  - Buena: respuesta razonablemente rápida, sin desvíos a herramientas irrelevantes.
  - La salida fue en texto plano y con información coherente sobre el marcador.
- Problema de contrato:
  - El flujo observado usó únicamente `web_search`.
  - La skill requiere expresamente:
    - ejecutar `web_fetch` sobre al menos una URL concreta;
    - basar la respuesta solo en contenido de `web_search` + `web_fetch`.
  - Por tanto, incluso con un buen resultado UX, hay una violación del contrato interno de la skill que debe corregirse:
    - cuando hay URLs disponibles en los resultados de búsqueda, `live_fact_lookup` debe seleccionar al menos una y hacer `web_fetch` antes de la respuesta final.

Resultado de búsqueda natural sin slash command
-----------------------------------------------

- Input tipo: “busca el resultado entre España y Cabo Verde”.
- El agente, sin la restricción explícita de la skill, terminó:
  - visitando YouTube vía `web_fetch`;
  - planteando `ask_user` sin necesidad;
  - visitando páginas de predicciones;
  - inventando una llamada a `mcp_call` con `MCP_SERVER_NAME`;
  - derivando a comandos de filesystem (`tree`, `ls`).
- Conclusión:
  - Para queries naturales sin slash, el arnés debe guiar al modelo a:
    - permanecer en el espacio de herramientas web/factuales (`web_search`, `web_fetch`);
    - evitar filesystem salvo que el usuario lo pida explícitamente;
    - no introducir MCP ficticios como forma de “salida creativa”.

Caso Bitcoin / Coinbase / HTTP 403
----------------------------------

- Contexto:
  - Se buscó el precio actual de Bitcoin y se intentó leer Coinbase como una de las fuentes.
- Observación clave:
  - `web_fetch` contra `https://www.coinbase.com/en-es/converter/btc/usd` devolvió `HTTP 403`.
- Interpretación:
  - Muchos sitios financieros y de intercambio bloquean scraping automático o tráfico no interactivo.
  - Un `403` en este contexto no es necesariamente un bug del fetcher ni de la infraestructura del arnés.
  - El problema está en la estrategia del agente tras recibir el `403`.

Diagnóstico del 403 y del bug real
----------------------------------

- `HTTP 403` desde Coinbase:
  - Es coherente con políticas anti-bot y anti-scraping.
  - El arnés ya detecta y propaga el error en el resultado de `web_fetch`.
- Bug real (a nivel de agente/harness):
  - No existía una lógica de fallback suficientemente robusta:
    - el agente podía:
      - repetir la misma consulta o variaciones mínimas sin aportar valor;
      - inventar herramientas MCP o URLs alternativas;
      - derivar a filesystem (`ls`, `tree`) en una tarea puramente web/factual;
      - preguntar al usuario “qué hacer” incluso con suficiente información parcial de snippets.
- Estado tras los cambios:
  - `web_fetch_failed_nudge`:
    - Detecta errores HTTP como `400`, `401`, `403`, `404`, `429`, `500`, `502`, `503`.
    - Inserta un mensaje que:
      - explica que el URL puede ser incorrecto o bloqueado;
      - prohíbe adivinar otros URLs;
      - instruye al modelo a volver a `web_search` con una query textual.
  - Esto no soluciona por completo todos los patrones de repetición, pero:
    - encamina el flujo hacia “un intento adicional razonable” en vez de bucles abiertos;
    - acota la herramienta al espacio web en vez de saltar a filesystem o MCP inventados.

Necesidad de fallback robusto
-----------------------------

Aunque ya hay mejoras, sigue siendo necesario reforzar la lógica de fallback para consultas factuales/live:

- Máximo una búsqueda alternativa razonable:
  - Ante `web_fetch` con `403` (u otros HTTP duros), se debería permitir:
    - como mucho, una búsqueda alternativa con `web_search`;
    - seleccionar una o dos fuentes adicionales plausibles;
    - si también fallan o son débiles, cerrar la respuesta.
- No repetir la misma query:
  - El arnés ya tiene detección de bucles de tool calls (`stuck_rounds`).
  - Para tareas web/factuales, conviene que el patrón “misma query de `web_search` + mismo tipo de `web_fetch` fallido” cuente como bucle fuerte y dispare el cierre.
- No usar MCP inventado:
  - Las respuestas deben restringirse a MCP servers reales y declarados.
  - Cualquier placeholder (`MCP_SERVER_NAME`, etc.) debe quedar explícitamente prohibido en este tipo de tareas.
- No usar filesystem en tareas web/factuales:
  - Para queries del estilo “resultado de un partido”, “precio actual”, “última versión estable”, etc.:
    - las herramientas preferidas son `web_search` y `web_fetch`;
    - tools de filesystem (`ls`, `tree`, `read_file`, etc.) deberían estar vetadas salvo que el usuario pida explícitamente inspeccionar archivos locales.
- Responder con caveat si solo hay snippets:
  - Si solo se han conseguido snippets parciales de `web_search` (o si `web_fetch` falla sistemáticamente):
    - la respuesta debe incluir explícitamente que no se ha podido verificar el dato en fuentes completas;
    - el formato de `live_fact_lookup` ya contempla un texto tipo:
      - “No lo puedo verificar con claridad en la fuente consultada.”
  - Es preferible una respuesta incompleta pero honesta, apoyada en snippets, a inventar un valor “plausible”.
- Obedecer “stop tools / responde con lo que sabes”:
  - Cuando el usuario pide explícitamente que se dejen de usar tools:
    - el bucle debe:
      - dejar de encolar nuevas llamadas a `web_search`/`web_fetch` (o cualquier otra tool);
      - dar una respuesta final basada solo en los resultados ya acumulados.

Riesgos pendientes
------------------

- El nudge hacia `web_search` y el nudge ante `web_fetch` fallido mejoran el comportamiento, pero no garantizan por sí solos:
  - que el modelo deje de sugerir MCP inventados;
  - que nunca derive a filesystem si los prompts de sistema no son lo bastante claros para “tareas web”.
- El contrato de `live_fact_lookup` aún puede ser violado en runtime si:
  - el modelo decide “atajar” y contestar solo con snippets de `web_search` sin pasar por `web_fetch`.
- La lógica de bucles general (`stuck_rounds`) es agnóstica al tipo de herramienta:
  - sigue siendo posible que combinaciones de `web_search` y `web_fetch` se repitan de forma no trivial sin superar el umbral configurado.
- Sin una política explícita de “tool budget” por tipo de tarea, siempre quedará cierto margen para que el modelo se “vaya por las ramas” antes de converger.

Próximos pasos priorizados
---------------------------

1. **Endurecer la skill `live_fact_lookup`:**
   - Añadir lógica de validación en el arnés que:
     - verifique que, si `web_search` encontró URLs, se ha llamado al menos una vez a `web_fetch` antes de aceptar una respuesta final de la skill.
     - marque explícitamente como error de contrato cualquier respuesta final sin `web_fetch` cuando `web_fetch` estaba disponible.
2. **Fallback específico para `403` y errores HTTP duros:**
   - Extender los tests para cubrir:
     - un único intento de `web_search` adicional ante `403`;
     - cierre controlado con caveat si la segunda fuente vuelve a fallar.
3. **Control de herramientas permitido para queries web/factuales naturales:**
   - Añadir una capa de clasificación ligera de intención que:
     - detecte queries de tipo “resultado/score/precio/versión/fecha de evento”;
     - limite automáticamente el espacio de herramientas a `web_search` y `web_fetch` en esos casos.
4. **Obediencia fuerte a “deja de repetir” y “responde con lo que sabes”:**
   - Añadir tests que simulen usuarios pidiendo explícitamente “deja de repetir tools / responde con lo que ya sabes” y verifiquen:
     - que no se ejecutan más tools tras esa instrucción;
     - que se devuelve una respuesta final basada en el historial de snippets.
5. **Guardas contra MCP y filesystem no pertinentes:**
   - Meter checks adicionales en el bucle para:
     - bloquear `mcp_call` con nombres placeholder;
     - bloquear filesystem en tareas marcadas como web/factuales salvo override explícito del usuario.

Tests de regresión propuestos
-----------------------------

No todos estos tests están implementados aún, pero se proponen como cobertura de regresión deseada para cerrar el hueco observado hoy:

- `test_live_fact_lookup_requires_fetch_before_final_when_fetch_available`
  - Verifica que `live_fact_lookup` no puede finalizar sin al menos un `web_fetch` cuando hay URLs disponibles en los resultados de `web_search`.
- `test_live_fact_lookup_fetch_403_fallback_does_not_repeat_search`
  - Simula un `web_fetch` con `HTTP 403` y comprueba que:
    - se hace como mucho un intento adicional de `web_search`;
    - no se repite indefinidamente la misma query.
- `test_live_fact_lookup_fetch_403_answers_with_snippet_caveat`
  - Comprueba que, si tras `403` solo hay snippets de `web_search`, la respuesta:
    - usa esos snippets de forma explícita;
    - incluye una advertencia de que no se ha podido verificar con claridad.
- `test_user_stop_repeating_tools_forces_final_answer`
  - Verifica que, tras una instrucción explícita del usuario para dejar de usar tools:
    - el agente cierra el bucle;
    - no se generan más tool calls.
- `test_no_duplicate_web_search_same_query_in_single_fact_task`
  - Garantiza que, para una tarea factual concreta, no se repite la misma query de `web_search` más de una vez salvo cambios significativos.
- `test_natural_fact_query_does_not_use_filesystem`
  - Comprueba que consultas naturales del tipo “resultado de partido / precio actual / última versión” no activan tools de filesystem salvo petición explícita.
- `test_natural_fact_query_does_not_call_placeholder_mcp`
  - Verifica que no se llegan a ejecutar `mcp_call` con nombres genéricos o placeholders en este tipo de tareas.
- `test_slash_skill_inside_ask_user_not_treated_as_plain_text`
  - Asegura que, si en una interacción mediada por `ask_user` el usuario escribe un slash command, este no se “pierde” como texto plano sino que se interpreta correctamente según la lógica de skills.

