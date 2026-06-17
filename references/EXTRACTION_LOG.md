# Extraction log (reverse engineering)

Which ideas we took from each reference repo to build **IAmultiagentica**.
We did not copy code or use those projects as dependencies: we read, understood, and rewrote in our own Python.

**Scope:** the `ci2lab/harness/` module + CLI + pipeline + hardware/router/catalog

---

## Quick summary

| Repo | Main role | What it gave us |
|------|-----------|-----------------|
| Odysseus | Technical base | How to make an agent work with local models; the idea of hardware detection + a model catalog |
| Deep Agents | Behavior | How the agent should act and speak |
| Claude Code | Best practices | How to use tools with good judgment |
| OpenCode | Security and order | How to ask for permission and organize tools |

---

## Odysseus (`../odysseus-dev/`)

**Why we looked at it:** It is the closest to what we wanted — a Python agent built for Ollama and open-source models.

### What we took

- The **agent loop**: think → use a tool → see the result → repeat until answering.
- The idea of supporting **multiple ways** a model can request tools (not all of them speak the same way).
- The **list of coding tools**: read, search, list, write, edit, bash.
- **Avoiding infinite loops** when the model repeats the same thing over and over.
- **Limiting** long commands and outputs so the conversation doesn't hang or get flooded.
- Keeping the agent **inside the project folder** for safety.
- The idea of **scanning the hardware and scoring which model fits**, plus a model catalog (from its README + `services/hwfit/`).

### What we did not take

- The web interface, email, cooking recipes, MCP integration.
- Dozens of extra tools not needed for coding.
- Its database, its full backend, or its giant loop as-is.

---

## Deep Agents (`../deepagents-main/`)

**Why we looked at it:** It has a clear write-up on **how a good agent should behave**, without depending on a specific product.

### What we took

- The **agent's tone**: get to the point, act instead of just promising, verify the result.
- The **basic set** of file tools (list, read, search, write, edit).
- The idea of **asking for confirmation** before delicate actions (write, edit, bash).

### What we did not take

- LangChain, LangGraph, or its agent framework.
- Subagents, advanced planning, or long-term memory.
- Its full filesystem middleware.

---

## Claude Code (`../claude-code-main/`)

**Why we looked at it:** It is the quality reference for prompts and for **when** to use each tool.

### What we took

- The rule to **prefer reading and searching** before running terminal commands.
- **Clear descriptions** of each tool so the model knows when to use it.
- Reading files **with line numbers** to cite snippets precisely.
- The general loop idea: question → tools → answer (without copying its TypeScript code).

### What we did not take

- The full commercial product: context compaction, hooks, analytics, subagents.
- Huge prompts designed for very large models.
- Integration with Anthropic, MCP, plan mode, etc.

---

## OpenCode (`../opencode-dev/`)

**Why we looked at it:** It organizes tools well and **asks the user** before running sensitive actions.

### What we took

- **Asking before running** bash, writing, or editing files.
- A **single registry** where all the tools live (definition + execution).
- **Shortening very long outputs** so the conversation isn't filled with noise.

### What we did not take

- Its tech stack (Effect-TS, monorepo, plugins).
- Advanced sessions, YAML permission rules, MCP integration.
- Strict argument validation (left as a future improvement).

---

## What is ours (not from those repos)

- The **shared contracts** between modules.
- The **CLI** (`doctor`, direct prompt, chat, sessions).
- The **client** that talks to Ollama and the terminal streaming.
- **Saved sessions** on disk and the interactive REPL mode.
- The **pipeline** that connects router and harness (with a default fallback model).
- The harness **tests**.

---

## Detailed log (by destination)

| Date | Source | What was extracted | Destination in ci2lab/ |
|------|--------|--------------------|------------------------|
| 2026-06 | Odysseus | Multi-round ReAct loop | `harness/query/loop.py` |
| 2026-06 | Odysseus | Tool parser (multiple formats) | `harness/parsing.py` |
| 2026-06 | Odysseus | Tool schemas and catalog | `harness/tools/` (schemas, dispatch, executor) |
| 2026-06 | Odysseus | Message format with tool history | `harness/messages.py` |
| 2026-06 | Odysseus | Working-folder boundary | `harness/tools/paths.py` |
| 2026-06-09 | Odysseus (README + `services/hwfit/`) | The idea of "hardware scan + fit scoring + model catalog"; no code copied | `hardware/`, `router/`, `catalog/models.json` |
| 2026-06 | Deep Agents | Agent behavior and tone | `harness/prompts/system.md` |
| 2026-06 | Deep Agents | Minimal set of file tools | `harness/tools/filesystem.py` |
| 2026-06 | Deep Agents | Confirmation on delicate actions | `harness/security/permissions.py` |
| 2026-06 | Claude Code | Tool-usage rules in the prompt | `harness/prompts/system.md` |
| 2026-06 | Claude Code | Reading with numbered lines | `harness/tools/filesystem.py` |
| 2026-06 | OpenCode | Asking permission before running | `harness/security/permissions.py` |
| 2026-06 | OpenCode | Unified registry + output truncation | `harness/tools/registry.py` |
| 2026-06 | — (ours) | CLI, REPL, sessions, LLM client | `cli/`, `harness/repl.py`, `pipeline.py` |
| 2026-06-12 | — (ours) | Harness refactor + integration | `harness/query/`, `harness/context/`, `harness/security/`, `console.py` |

---

## Pending extraction (future phases)

| Source | Idea | What it would be for |
|--------|------|----------------------|
| Claude Code | Run reads in parallel | Faster repo exploration |
| Odysseus | Advanced history compaction | Very long conversations |
| OpenCode | Strict argument validation | Fewer model errors when calling tools |
