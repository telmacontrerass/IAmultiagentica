# Research Skills (P1.5)

## 1) Objetivo

Las research skills convierten una herramienta base (`web_fetch`) en flujos evaluables y deterministas para análisis técnico con evidencia.

Objetivo de P1.5:
- partir de una URL controlada (fixture local),
- extraer hechos verificables,
- producir salidas estructuradas en JSON,
- validar contrato y orquestación en tests offline.

## 2) Tool vs Skill

- `web_fetch` (tool primitiva, read-only):
  - descarga contenido `http/https`,
  - sigue redirecciones,
  - limpia HTML,
  - recorta respuesta larga,
  - no modifica archivos ni ejecuta acciones destructivas.

- `research_web_doc_review` (skill evaluable):
  - usa `web_fetch`,
  - revisa una documentación web controlada,
  - exige evidencia textual y límites no verificados.

- `research_web_vs_repo` (skill documentación vs código):
  - usa `web_fetch` + `read_file`,
  - compara hechos documentales con observaciones del repo local,
  - separa coincidencias, gaps/riesgos y recomendaciones.

## 3) Skills actuales

### `research_web_doc_review`

- Herramientas permitidas: `web_fetch`
- Entrada: una URL exacta
- Salida esperada (JSON):
  - `url`, `title`, `key_points`, `relevant_api_or_concepts`,
  - `constraints_or_warnings`, `quoted_evidence`,
  - `practical_recommendations`, `unknowns_or_not_verified`
- Qué valida el test:
  - JSON con claves exactas
  - evidencia textual procedente de la página fixture
  - ausencia de fuentes externas inventadas
  - presencia de límites/no cubierto
- Limitaciones actuales:
  - evaluación semántica del modelo real no cubierta en esta fase

### `research_web_vs_repo`

- Herramientas permitidas: `web_fetch`, `read_file`
- Entrada: URL + uno o más archivos locales (fase actual: 1 archivo)
- Salida esperada (JSON):
  - `url`, `local_files_reviewed`, `doc_facts`, `repo_observations`,
  - `matches`, `gaps_or_risks`, `recommended_changes`,
  - `changes_not_recommended`, `quoted_evidence`,
  - `unknowns_or_not_verified`
- Qué valida el test:
  - JSON con claves exactas
  - URL presente
  - archivo local listado en `local_files_reviewed`
  - evidencia documental + observaciones concretas de código
  - al menos un `match`, un `gap_or_risk`, una recomendación y un cambio no recomendado
  - ausencia de fuentes externas inventadas
- Limitaciones actuales:
  - caso monofichero en test (multiarchivo queda para fase posterior)

## 4) Enfoque de seguridad

- Tests 100% offline/deterministas.
- Sin dependencia de internet en CI.
- Sin modificación de archivos durante research skills.
- Sin fuentes externas no proporcionadas por la entrada.
- Toolset restringido por skill (`allowed_tools`).

## 5) Comandos de verificación

```bash
pytest tests/test_research_skills.py -q
pytest tests/ -q
```

## 6) Limitaciones honestas

- Los tests actuales usan LLM mock determinista.
- Validan contrato/orquestación y evidencia estructural.
- No validan todavía la calidad semántica completa de modelos vivos.
- La evaluación live queda explícitamente para una fase posterior.

## 7) Roadmap

- Evaluación semántica live opcional (fuera de CI por defecto).
- Extensión a comparación multiarchivo.
- Comparación multi-fuente con corpus controlado.
- Evaluación de estado del arte con corpus cerrado.
- Extracción de papers como capacidad posterior (no incluida en P1.5).
