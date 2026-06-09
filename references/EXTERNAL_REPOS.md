# Repositorios de referencia (solo lectura)

Estos repositorios viven **fuera** de `IAmultiagentica/`, en la carpeta padre `Ci2Lab/`.
No son dependencias del proyecto. Se usan solo para ingeniería inversa de prompts, bucles agénticos y patrones.

| Carpeta (en `../`) | Uso |
|--------------------|-----|
| `claude-code-main/` | System prompts, descripciones de herramientas, bucle query |
| `odysseus-dev/` | Bucle agent_loop, tool_parsing, schemas, ejecución |
| `opencode-dev/` | Registry de tools, permisos, session loop |
| `deepagents-main/` | BASE_AGENT_PROMPT, filesystem middleware |

## Reglas

- **No** `import` ni `pip install` desde estos repos.
- **No** copiar carpetas enteras al paquete `ci2lab/`.
- Documentar en `references/EXTRACTION_LOG.md` qué se extrajo y a qué archivo de destino.

## Rutas relativas desde IAmultiagentica

```text
../claude-code-main/
../odysseus-dev/
../opencode-dev/
../deepagents-main/
```
