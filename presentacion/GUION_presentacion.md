# Guión de presentación — Florentino (CI2LAB · Comillas ICAI)

**Duración:** 7 min de exposición + 7 min de preguntas
**Deck:** `Florentino_presentacion_v3.pptx` — 12 diapositivas (versión completa: estilo
Comillas + profundidad técnica de ci2lab)
**Ritmo objetivo:** ~130 palabras/min. Está calibrado para ~6:55; es **ajustado**.

> El texto en *cursiva* es lo que se dice. Con 12 diapositivas en 7 min hay que ir con
> ritmo. Si necesitáis holgura, ver **“Ruta de 7 min estricta”** al final.

### Reparto sugerido (5 ponentes)
| Ponente | Diapositivas | Bloque |
|---------|--------------|--------|
| 1 | 1 – 2 | Portada + contexto (Cátedra/Reto 9) |
| 2 | 3 – 4 | Qué es + los 3 pasos |
| 3 | 5 – 6 | Núcleo técnico (arquitectura + agente) |
| 4 | 7 – 8 – 9 | Uso + casos + tradeoff |
| 5 | 10 – 11 – 12 | Fiabilidad + honestidad + cierre |

---

## ⏱️ 1 — Portada · (0:00 – 0:15)
*Buenos días. Somos el equipo del Reto 9 del CI2LAB y os presentamos **Florentino**:
IA agéntica que corre **en local**, para docencia e investigación.*

## ⏱️ 2 — La Cátedra y el Reto 9 · (0:15 – 0:55)
*Nace en la **Cátedra de Industria Inteligente** de Comillas ICAI, dentro del
**CI2LAB**, donde resolvemos retos reales de empresas patrono como Repsol, Enagás o
Endesa. El **Reto 9** parte de una observación: hoy el acceso a los modelos es barato
porque las grandes empresas subvencionan el precio, pero la **facturación cambiará** y
con uso intensivo puede dispararse. Y sobre todo, **dependes de un proveedor externo**:
sujeto a cambios de modelo, límites o a que retiren el servicio. Florentino responde a
ese riesgo.*

## ⏱️ 3 — ¿Qué es Florentino? · (0:55 – 1:25)
*Una alternativa **open source** que replica el lazo agéntico de Claude Code,
ejecutándose por completo en tu máquina. Es un bucle: lanzas una petición y el agente
**reúne contexto, actúa** con herramientas y **verifica**, repitiéndolo hasta terminar.
Y en cualquier momento **tú intervienes**: interrumpes, guías o añades contexto.*

## ⏱️ 4 — Florentino, en tres pasos · (1:25 – 2:05)
*¿Cómo pasas de cero a un agente funcionando? Tres pasos. **Uno, perfila el hardware**:
detecta tu RAM, VRAM y GPU. **Dos, recomienda el modelo**: de un catálogo de 86, filtra
los que caben en tu máquina y los puntúa por tarea. **Tres, ejecuta el agente**: el lazo
ReAct con 28 herramientas. Todo **100% local** —coste cero, privacidad, offline— y con un
**backend enchufable**: Ollama, vLLM o LM Studio; cambiar es solo configuración.*

## ⏱️ 5 — Arquitectura: el recorrido de una petición · (2:05 – 2:50)
*Por dentro, el recorrido es claro: entras por terminal o web; la configuración se
resuelve con una **precedencia definida** —defaults, yaml, entorno, flags—; el pipeline
y el router eligen el modelo; y arranca el lazo ReAct. Lo clave: se apoya en dos
**costuras enchufables**. Los **backends** abstraen el transporte del modelo —un proveedor
nuevo es una subclase— y las **herramientas** se parsean, despachan y ejecutan —añadir una
son cuatro registros que un test sincroniza. **Crecer no obliga a tocar el núcleo.***

## ⏱️ 6 — El agente: un ecosistema · (2:50 – 3:30)
*El agente es un **ecosistema**: 28 herramientas —bash, ficheros, git, web, visión, PDF—;
extensible con MCP y skills; memoria de proyecto; y un modo multiagente con revisión
entre pares. Y la **seguridad**, que es parte del núcleo: permisos deny/ask/allow,
perfiles estricto/estándar/auditoría y guardas duras que bloquean bash peligroso. El
agente toca tus ficheros y ejecuta comandos: **la seguridad no es opcional**.*

## ⏱️ 7 — Formas de uso · (3:30 – 4:00)
*Dos maneras. La **terminal**, para perfiles técnicos: máximo control. Y la **web**
—Florentino—, con las mismas funcionalidades sin escribir un comando, pensada para todo
el profesorado e investigadores: te dice qué modelos caben y arranca el agente con un
clic.*

## ⏱️ 8 — Casos de uso (skills) · (4:00 – 4:35)
*Cuatro **skills** para una cátedra: **revisión de papers** —adaptada a revista y rúbrica,
con citas verificadas—; **creación de slides**; **corrección de exámenes** —con rúbricas y
feedback—; y **lectura de documentos** —resume PDFs, extrae ideas y genera preguntas. Todo
sin que ningún documento salga de la máquina.*

## ⏱️ 9 — Usar este sistema implica un tradeoff · (4:35 – 5:15)
*Con honestidad, es un **intercambio**. Se cede **potencia bruta** —un modelo local razona
peor que un frontier—, hay un **techo de hardware** y hay que **mantener** el entorno. Pero
se gana **privacidad total**, **independencia** —sin API key ni lock-in, y offline— y
**confianza verificable**. Y en eso último está nuestra contribución.*

## ⏱️ 10 — Confianza verificable · (5:15 – 6:05)
*Si el modelo es más débil, ¿cómo confías en él? Nuestra aportación es **medirlo**. El
estado del arte **confunde el harness con el modelo**; Florentino **fija el modelo y varía
el andamiaje** para aislar de dónde viene la fiabilidad. Medimos el **éxito real** —no solo
“¿terminó?”, sino los éxitos falsos—, la **atribución de fallo** —modelo, harness o
entorno— y una **taxonomía** con un caso propio, `tool_trace_failed`: correcto pero
imposible de demostrar.*

## ⏱️ 11 — Honestidad: lo local tiene un techo · (6:05 – 6:40)
*Y no ocultamos los límites. La causa raíz es el **techo de capacidad** del hardware de
consumo. Distinguimos lo **inherente** —necesita muletas, no hay árbitro fuerte, es un
punto único de fallo— de lo **solucionable, que ya estamos cerrando**: arreglamos la
telemetría del banco, añadimos intervalos de confianza bootstrap y un chequeo pre-vuelo.
La fortaleza es no prometer lo primero.*

## ⏱️ 12 — Cierre · (6:40 – 6:55)
*En una frase: **un asistente que trabaja para ti, sin que tus datos salgan de casa**.
Privado, independiente y fiable. Gracias — abiertos a vuestras preguntas.*

[Pasar a preguntas]

---

### Ruta de 7 min estricta (si vais justos)
El deck tiene mucho contenido. Para asegurar los 7 min, las diapositivas más
comprimibles/omitibles son, por orden: **8 (Casos de uso)** → **11 (Honestidad)** →
fusionar **3 y 4**. Quitando la 8 y la 11 os quedan **10 diapositivas** muy holgadas.

---
---

# 🎯 Preparación de preguntas (los otros 7 minutos)

### 1. ¿Por qué no usar ChatGPT o Claude?
Privacidad (los datos no salen de la máquina), independencia (sin API key ni lock-in) y
coste (cero por token). No sustituye a un frontier en capacidad pura; resuelve el riesgo
de depender de un proveedor externo —el Reto 9.

### 2. ¿En qué se diferencia de usar Ollama a secas?
Ollama solo **sirve** el modelo. Florentino añade el resto: perfila hardware y recomienda
modelo, el lazo con 28 herramientas, seguridad, sesiones, la web y el banco que **mide**
la fiabilidad. Ollama es una pieza (el backend), no el producto.

### 3. ¿Cómo se añade un modelo, una herramienta o un backend?
- **Modelo:** una entrada en `catalog/models.json`.
- **Herramienta:** los 4 registros (`TOOL_NAMES`, `DISPATCH`, schema, capabilities); un
  test falla si se desincronizan.
- **Backend:** implementar `LLMBackend` y registrarlo en el factory (diapo 5).

### 4. ¿Es seguro dar acceso a ficheros y comandos?
Permisos deny/ask/allow, perfiles, blocklist y confirmación. **Honestos**: no hay sandbox
de sistema operativo real y la protección de secretos es por nombre de fichero, no por
redacción de valores. Mitigación seria, no garantía.

### 5. ¿Qué modelos usa y cómo se eligen?
Catálogo de ~86 modelos open source. Florentino perfila tu máquina y **recomienda** los
que caben; tú eliges (Qwen2.5-Coder 7B, Llama 3.1 8B…). No hay auto-descarga: el usuario
hace `ollama pull`.

### 6. ¿Cómo medís la "fiabilidad"?
Con un **oracle**, no un LLM-juez. El banco reporta Pass@k, tokens/coste/latencia, tasa
de **éxito falso**, éxito con evidencia y violaciones de herramientas, con intervalos de
confianza bootstrap.

### 7. ¿Qué es `tool_trace_failed`?
Resultado **correcto** pero el agente **no puede demostrar** cómo lo obtuvo. Un banco que
solo mira éxito/fracaso lo contaría como éxito, ocultando que la procedencia no es fiable.

### 8. ¿Qué es exactamente el "lazo ReAct"?
Razonar → actuar (herramienta) → observar → repetir, con guardarraíles (detección de
bucles, corte por errores, nudges) para que un modelo pequeño no se atasque.

### 9. ¿Qué es lo "multiagente"?
Roles + revisión entre pares con evidencia. Honestamente: por defecto es el mismo modelo
con distintos sombreros; el cierre determinista con evidencia es la ruta opt-in
`--multi-agent`.

### 10. ¿Cuál es la mayor limitación?
El techo del modelo local + la falta de árbitro fuerte: más débil **y** sin inteligencia
superior a la que escalar. Cerrarlo del todo exigiría un backend cloud opcional, que
rompería la promesa 100% local. Es decisión de producto.

### 11. ¿Qué garantías de calidad de código tiene?
Cuatro puertas en CI (Python 3.11 y 3.12): lint, formato, tipos (mypy) y ~905 tests.

### 12. ¿Por qué "Florentino"?
Es el nombre amable del proyecto (la web se llama así); por debajo, la herramienta y el
paquete se llaman `ci2lab`.

---

## Notas para los ponentes
- El deck ya lleva **vuestros nombres** en la portada. Nada que rellenar.
- Cifras memorizables: **~86 modelos**, **28 herramientas**, lazo **reúne→actúa→
  verifica**, **3 pasos**, **4 skills**, **~905 tests**, backend **enchufable**.
- Mejores bazas ante tribunal técnico: la **arquitectura** (5), la **medición de la
  fiabilidad** (10) y la **honestidad** de los límites (9 y 11).
