# Known limitations — Ci2Lab

## Pipeline ↔ router integration

| Limitation | Detail |
|------------|--------|
| The router does not auto-select a model in chat | `ci2lab models recommend` suggests; the user picks with `--model`. |
| `tool_mode` from the catalog | `prepare_session()` + `build_model_selection()` apply the catalog mode; override with `--tool-mode` or yaml. |
| Uncataloged tags | Unknown models default to `tool_mode: fenced`. |
| No auto-pull | `runtime/ensure.py` does not exist; the user must run `ollama pull`. |
| `ci2lab agent --session` without history | `--session` saves but does not load previous messages (`chat --session` and the UI do). |
| `resolve_model()` unused in production | Optional API; chat/agent/UI use `build_model_selection()`. |

## Out of scope (for now)

| Area | Status |
|------|--------|
| Automatic runtime (`ollama pull` / ensure) | Not implemented |
| Git snapshot / rollback / auto-commit | Not implemented |
| Per-turn multi-model routing | Not implemented |
| Live per-model benchmark of the catalog | Static scores in `models.json` only |
| Vector memory across sessions | Not implemented |
| Claude-Code-style extensible hooks | Not implemented |

## Integrated

| Area | Status |
|------|--------|
| MCP client (stdio) | Done — `.ci2lab/mcp.json` |
| Workspace skills | Done — `.ci2lab/skills/*/SKILL.md` |
| Project memory | Done — `CI2LAB.md`, `AGENTS.md` |
| Local web UI | Done — `ci2lab ui` |
| Context compaction | Done — `harness/context/` |
| Security engines | Done — `ci2lab/security/` (`ci2lab`, `claude_experimental`, …) |
| 25 built-in tools | Done — `harness/tools/schemas_parts/registry.py` |

## Localization

| Limitation | Detail |
|------------|--------|
| Web frontend still in Spanish | The agent system prompt, the terminal/CLI UI, and tool outputs are English, but the web UI page text (`ci2lab/ui/static/index.html`, `app.js`) is still Spanish. |
| A few tool output strings still in Spanish | Some filesystem tool messages (e.g. `grep` "no matches" notices) remain Spanish; the agent and CLI surfaces are otherwise English. |

## Security and sandbox

See [`SECURITY_POLICY.md`](SECURITY_POLICY.md).

| Limitation | Detail |
|------------|--------|
| No OS/container sandbox | Confirmation + blocklist; no seccomp or isolated network |
| Paths | `resolve_path()` confines access to the workspace |
| Sensitive files | Heuristic in `secret_files`; not a perfect classifier |
| `bash` with `shell=True` | `--yes` does not skip the workspace blocklist |

## Harness operation

| Limitation | Detail |
|------------|--------|
| Heterogeneous parser | Local models may print tool calls as plain text |
| Task-agnostic loop | The loop has no per-topic special cases; robustness comes from generic mechanisms (loop detection, error-streak cutoff, workspace-policy handling, edit follow-ups, `web_fetch`→`web_search` redirect, and a few recovery nudges). |
| Compaction | Old history is summarized or trimmed |
| Coarse trim | ~4 characters/token |
| REPL / sessions | `~/.ci2lab/sessions/`; resume with `chat --session ID` |
| CLI flags | Agent flags go **before** the subcommand |
| Terminal input | `prompt_toolkit` in REPL/ask_user; confirmations use `input()` |

## Tests

Run `python -m pytest -q`. Covers the harness, tools, MCP, skills, router, CLI, and security.
