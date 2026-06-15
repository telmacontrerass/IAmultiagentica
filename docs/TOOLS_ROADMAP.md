# Hoja de ruta de herramientas Ci2Lab

## Estado actual (24 herramientas built-in + MCP dinámico)

| Herramienta | Tipo |
|-------------|------|
| `read_file`, `read_document`, `inspect_file`, `file_info`, `tree`, `ls`, `glob`, `grep` | lectura / exploración |
| `write_file`, `write_docx`, `docx_to_pdf`, `pdf_to_docx`, `edit_file`, `apply_patch`, `fill_docx_template`, `notebook_edit` | escritura / conversión |
| `bash`, `git_status`, `git_diff` | shell / git |
| `todo_write`, `ask_user`, `web_fetch` | flujo / usuario |
| `skill`, `mcp_call` | skills + MCP fallback |
| `mcp__*` | herramientas MCP dinámicas (servidores en `.ci2lab/mcp.json`) |

**Arquitectura del registro:**

- `harness/tools/schemas.py` — `TOOL_NAMES` y schemas OpenAI
- `harness/tools/dispatch.py` — tabla name → implementación
- `harness/tools/executor.py` — `execute_tool`, permisos, previews, security gate
- `harness/tools/registry.py` — re-export público

**Extensiones relacionadas (no son tools del dispatch):**

- Skills: `.ci2lab/skills/*/SKILL.md` → tool `skill`
- Project memory: `CI2LAB.md`, `AGENTS.md` → inyectado en system prompt

## Candidatas futuras

| Tool | Prioridad | Notas |
|------|-----------|-------|
| `run_tests` | Alta | wrapper seguro sobre pytest |
| Registro declarativo único | Media | unificar schemas + dispatch + COMPACTABLE_TOOLS |
| `runtime/ensure.py` | Alta | `ollama pull` automático |

## Descartadas por ahora

- Sub-agentes con ventana aislada
- Marketplace de plugins
