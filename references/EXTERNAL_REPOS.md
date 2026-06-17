# Reference repositories (read-only)

These repositories live **outside** `IAmultiagentica/`, in the parent `Ci2Lab/` folder.
They are not project dependencies. They are used only for reverse-engineering prompts, agentic loops, and patterns.

| Folder (in `../`) | Use |
|-------------------|-----|
| `claude-code-main/` | System prompts, tool descriptions, query loop |
| `odysseus-dev/` | agent_loop, tool_parsing, schemas, execution |
| `opencode-dev/` | Tool registry, permissions, session loop |
| `deepagents-main/` | BASE_AGENT_PROMPT, filesystem middleware |

## Rules

- **Do not** `import` or `pip install` from these repos.
- **Do not** copy whole folders into the `ci2lab/` package.
- Document in `references/EXTRACTION_LOG.md` what was extracted and into which destination file.

## Relative paths from IAmultiagentica

```text
../claude-code-main/
../odysseus-dev/
../opencode-dev/
../deepagents-main/
```
