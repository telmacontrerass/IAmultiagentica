# Ci2Lab tools roadmap

## Current state (25 built-in tools + dynamic MCP)

| Tool | Type |
|------|------|
| `read_file`, `read_document`, `inspect_file`, `file_info`, `tree`, `ls`, `glob`, `grep` | reading / exploration |
| `write_file`, `write_docx`, `docx_to_pdf`, `pdf_to_docx`, `edit_file`, `apply_patch`, `fill_docx_template`, `notebook_edit` | writing / conversion |
| `bash`, `git_status`, `git_diff` | shell / git |
| `todo_write`, `ask_user`, `web_search`, `web_fetch` | workflow / user |
| `skill`, `mcp_call` | skills + MCP fallback |
| `mcp__*` | dynamic MCP tools (servers in `.ci2lab/mcp.json`) |

The authoritative list is `TOOL_NAMES` in `harness/tools/schemas_parts/registry.py` (25 names; `mcp__*` tools are added dynamically).

**Registry architecture:**

- `harness/tools/schemas.py` — re-exports `TOOL_NAMES` and the OpenAI schemas
- `harness/tools/schemas_parts/` — `registry.py` (`TOOL_NAMES`) and the schema groups (`explore`, `edit`, `runtime`, `workflow`, `integrations`)
- `harness/tools/dispatch.py` — name → implementation table
- `harness/tools/executor.py` — permissions, previews, security gate
- `harness/tools/registry.py` — public re-export (`execute_tool`, `get_function_schemas`)

**Related extensions (not dispatch tools):**

- Skills: `.ci2lab/skills/*/SKILL.md` → `skill` tool
- Project memory: `CI2LAB.md`, `AGENTS.md` → injected into the system prompt

## Future candidates

| Tool | Priority | Notes |
|------|----------|-------|
| `run_tests` | High | safe wrapper around pytest |
| Single declarative registry | Medium | unify schemas + dispatch + compactable tools |
| `runtime/ensure.py` | High | automatic `ollama pull` |

## Dropped for now

- Subagents with an isolated window
- Plugin marketplace
