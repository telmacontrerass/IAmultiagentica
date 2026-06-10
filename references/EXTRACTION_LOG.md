# Registro de extracción (ingeniería inversa)

Qué ideas tomamos de cada repo de referencia para construir **IAmultiagentica**.
No copiamos código ni usamos esos proyectos como dependencias: leímos, entendimos y reescribimos en Python propio.

**Última actualización:** junio 2026 · **Alcance:** módulo `ci2lab/harness/` + CLI + pipeline + hardware/router/catalog

---

## Resumen rápido

| Repo | Rol principal | Qué nos aportó |
|------|---------------|----------------|
| Odysseus | Base técnica | Cómo hacer funcionar un agente con modelos locales; idea de detección de hardware + catálogo de modelos |
| Deep Agents | Comportamiento | Cómo debe actuar y hablar el agente |
| Claude Code | Buenas prácticas | Cómo usar las herramientas con criterio |
| OpenCode | Seguridad y orden | Cómo pedir permiso y organizar las tools |

---

## Odysseus (`../odysseus-dev/`)

**Por qué lo miramos:** Es el más parecido a lo que queríamos — agente en Python pensado para Ollama y modelos open source.

### Qué cogimos

- El **bucle del agente**: pensar → usar herramienta → ver resultado → repetir hasta responder.
- La idea de soportar **varias formas** en que un modelo pide herramientas (no todos hablan igual).
- La **lista de herramientas de programación**: leer, buscar, listar, escribir, editar, bash.
- **Evitar bucles infinitos** cuando el modelo repite lo mismo una y otra vez.
- **Limitar** comandos y salidas largas para no colgar ni saturar la conversación.
- Mantener al agente **dentro de la carpeta del proyecto** por seguridad.
- La idea de **escanear el hardware y puntuar qué modelo encaja**, más un catálogo de modelos (de su README + `services/hwfit/`).

### Qué no cogimos

- La interfaz web, el correo, recetas de cocina, integración MCP.
- Decenas de herramientas extra que no hacen falta para programar.
- Su base de datos, su backend completo ni el bucle gigante tal cual.

---

## Deep Agents (`../deepagents-main/`)

**Por qué lo miramos:** Tiene un texto claro sobre **cómo debe comportarse** un buen agente, sin depender de un producto concreto.

### Qué cogimos

- El **tono del agente**: ir al grano, actuar en lugar de solo prometer, comprobar el resultado.
- El **conjunto básico** de herramientas de archivos (listar, leer, buscar, escribir, editar).
- La idea de **pedir confirmación** antes de acciones delicadas (escribir, editar, bash).

### Qué no cogimos

- LangChain, LangGraph ni su framework de agentes.
- Sub-agentes, planificación avanzada ni memoria a largo plazo.
- Su middleware completo de filesystem.

---

## Claude Code (`../claude-code-main/`)

**Por qué lo miramos:** Es la referencia de calidad en prompts y en **cuándo** usar cada herramienta.

### Qué cogimos

- La regla de **preferir leer y buscar** antes de lanzar comandos en la terminal.
- **Descripciones claras** de cada herramienta para que el modelo sepa cuándo usarla.
- Leer archivos **con números de línea** para poder citar trozos con precisión.
- La idea general del bucle: pregunta → herramientas → respuesta (sin copiar su código TypeScript).

### Qué no cogimos

- Todo el producto comercial: compactación de contexto, hooks, analíticas, sub-agentes.
- Prompts enormes pensados para modelos muy grandes.
- Integración con Anthropic, MCP, modo plan, etc.

---

## OpenCode (`../opencode-dev/`)

**Por qué lo miramos:** Organiza bien las herramientas y **pregunta al usuario** antes de ejecutar cosas sensibles.

### Qué cogimos

- **Preguntar antes de ejecutar** bash, escribir o editar archivos.
- Un **registro único** donde viven todas las herramientas (definición + ejecución).
- **Acortar salidas muy largas** para no llenar la conversación de ruido.

### Qué no cogimos

- Su stack técnico (Effect-TS, monorepo, plugins).
- Sesiones avanzadas, reglas YAML de permisos, integración MCP.
- Validación estricta de argumentos (queda como mejora futura).

---

## Lo que es nuestro (no viene de esos repos)

- Los **contratos** compartidos entre módulos.
- La **CLI** (`doctor`, prompt directo, chat, sesiones).
- El **cliente** que habla con Ollama y el streaming en terminal.
- **Sesiones guardadas** en disco y modo REPL interactivo.
- El **pipeline** que conecta router y arnés (con modelo por defecto de respaldo).
- Los **tests** del arnés.

---

## Tabla de registro (detalle por destino)

| Fecha | Origen | Qué se extrajo | Destino en ci2lab/ |
|-------|--------|----------------|-------------------|
| 2026-06 | Odysseus | Bucle ReAct multi-ronda | `harness/loop.py` |
| 2026-06 | Odysseus | Parser de herramientas (varios formatos) | `harness/parsing.py` |
| 2026-06 | Odysseus | Schemas y catálogo de 7 tools | `harness/tools/` |
| 2026-06 | Odysseus | Formato de mensajes con historial de tools | `harness/messages.py` |
| 2026-06 | Odysseus | Límite de carpeta de trabajo | `harness/tools/paths.py` |
| 2026-06-09 | Odysseus (README + `services/hwfit/`) | Idea de "escaneo de hardware + puntuación de encaje + catálogo de modelos"; no se copió código | `hardware/`, `router/`, `catalog/models.json` |
| 2026-06 | Deep Agents | Comportamiento y tono del agente | `harness/prompts/system.md` |
| 2026-06 | Deep Agents | Set mínimo de tools de archivos | `harness/tools/filesystem.py` |
| 2026-06 | Deep Agents | Confirmación en acciones delicadas | `harness/permissions.py` |
| 2026-06 | Claude Code | Reglas de uso de tools en el prompt | `harness/prompts/system.md` |
| 2026-06 | Claude Code | Lectura con líneas numeradas | `harness/tools/filesystem.py` |
| 2026-06 | OpenCode | Preguntar permiso antes de ejecutar | `harness/permissions.py` |
| 2026-06 | OpenCode | Registry unificado + truncar salidas | `harness/tools/registry.py` |
| 2026-06 | — (propio) | CLI, REPL, sesiones, cliente LLM | `cli.py`, `harness/repl.py`, etc. |

---

## Pendiente de extracción (fases futuras)

| Origen | Idea | Para qué serviría |
|--------|------|-------------------|
| Claude Code | Ejecutar lecturas en paralelo | Más velocidad al explorar un repo |
| Odysseus | Compactación avanzada del historial | Conversaciones muy largas |
| OpenCode | Validación estricta de argumentos | Menos errores del modelo al llamar tools |
