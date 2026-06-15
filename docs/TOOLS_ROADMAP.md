# Hoja de ruta de herramientas Ci2Lab

## Estado actual (19 herramientas built-in + MCP dinámico)

| Herramienta | Tipo |
|-------------|------|
| `read_file`, `inspect_file`, `file_info`, `tree`, `ls`, `glob`, `grep` | lectura / exploración |
| `write_file`, `write_docx`, `edit_file`, `notebook_edit` | escritura |
| `bash`, `git_status`, `git_diff` | shell / git |
| `todo_write`, `ask_user`, `web_fetch` | flujo / usuario |
| `skill`, `mcp_call` | skills + MCP fallback |
| `mcp__*` | herramientas MCP dinámicas |

**Arquitectura (post-refactor):**

- `harness/tools/schemas.py` — nombres y schemas OpenAI
- `harness/tools/dispatch.py` — tabla name → implementación
- `harness/tools/executor.py` — `execute_tool`, permisos, previews
- `harness/tools/registry.py` — fachada de re-export

## Candidatas futuras

| Tool | Prioridad | Notas |
|------|-----------|-------|
| `run_tests` | Alta | wrapper seguro sobre pytest |
| `diff` (unified) | Media | complemento de `git_diff` |
| Paralelizar reads | Media | varios `read_file` en un turno |
| `runtime/ensure.py` | Alta | `ollama pull` automático |

## Descartadas por ahora

- Sub-agentes con ventana aislada (complejidad tipo Claude Code)
- Marketplace de plugins
