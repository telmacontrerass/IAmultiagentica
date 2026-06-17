# Audit of the current Ci2Lab harness flow

_Historical snapshot; may not reflect the current implementation._

**Date:** 2026-06-09
**Scope:** the MVP agentic harness in `IAmultiagentica` / the `ci2lab` package
**Method:** static code inspection, running `python -m ci2lab.cli --help`, `python -m ci2lab --help`, and the test suite.

**Update (cleanup phase, 2026-06-09):** see [§16](#16-update--cleanup-phase) and [`write_edit_tools_status.md`](write_edit_tools_status.md).

**Milestone close (2026-06-09):** harness validated mock + live — see [§18](#18-milestone-close--mocklive-validation) and [`live_eval_status.md`](live_eval_status.md). Sections §3–§15 are a historical snapshot of the first audit; §16–§18 reflect the state at the time.

**Update (2026-06-12):** structural refactor — CLI in `ci2lab/cli/`, loop in `harness/query/loop.py`, `pipeline.build_agent_config()`, console in `ci2lab/console.py`, MCP/skills/UI integrated. See [`STRUCTURE.md`](../STRUCTURE.md). Sections §3–§15 remain a historical snapshot except for stale file paths (`cli.py`, `harness/loop.py`).

**Update (2026-06-10):** `hardware/` and `router/` implemented in the CLI. See [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md).

---

## 1. Executive summary

The project has a **working ReAct agentic harness** integrated into the `ci2lab` package. The user invokes the CLI (`ci2lab` or `python -m ci2lab.cli`), which resolves config in `cli/runtime.py`, prepares a session via `pipeline.prepare_session`, builds `AgentConfig` with `pipeline.build_agent_config`, and delegates to `harness.query.loop.run_agent`. The loop calls Ollama over HTTP (OpenAI-compatible API), parses tool calls (native, XML, or fenced), runs tools, and returns results to the model until a final answer or `max_rounds`.

**Overall status:**

| Area | Status |
|------|--------|
| CLI + entry points | Working (`python -m ci2lab`, `python -m ci2lab.cli`) |
| ReAct loop | Complete (streaming, anti-loop, sessions) |
| LLM client (Ollama/httpx) | Actionable errors + exit codes |
| Reading tools (`ls`, `read_file`, `grep`, `glob`) | Implemented |
| `bash` with confirmation + blocklist | Confirmation + blocklist (even with `--yes`) |
| `write_file` / `edit_file` | Enabled in supervised mode — see `WRITE_POLICY.md` and `write_edit_tools_status.md` |
| `contracts/types.py` | **Already integrated** in the real flow (`ModelSelection` is the active contract) |
| `hardware/`, `router/`, `runtime/` | Skeleton only at the time (`__init__.py` with docstring) |
| Multi-model router | Not implemented; fell back to `default_selection` |
| Centralized config (`config.py`, `ci2lab.yaml`) | Implemented |
| `--workspace` | Alias of `--cwd` |
| Automated tests | Expanded suite (config, bash safety, llm errors, parsing) |

**Default model (unchanged in the cleanup):** `llama3.1:8b` via `config.DEFAULT_MODEL`, `pipeline.py`, or `CI2LAB_MODEL`. Override with `--model` or `ci2lab.yaml`.

**Structural discrepancy:** there are no separate `ls.py` or `read_file.py`; the filesystem tools live in `harness/tools/filesystem.py`.

---

## 2. Current repo state

### 2.1 Tree of relevant files

```text
IAmultiagentica/
├── pyproject.toml              # package, deps, ci2lab entrypoint, force-include prompts
├── README.md
├── ci2lab/
│   ├── __init__.py             # __version__
│   ├── __main__.py             # delegates to cli.main()
│   ├── cli.py                  # argparse, subcommands, orchestration
│   ├── pipeline.py             # prepare_session (router stub → default_selection)
│   ├── contracts/
│   │   ├── types.py            # ModelSelection, HardwareProfile, etc. — IN USE
│   │   └── README.md
│   ├── hardware/__init__.py    # skeleton
│   ├── router/__init__.py      # skeleton
│   ├── runtime/__init__.py     # skeleton
│   └── harness/
│       ├── __init__.py         # exports + default_selection()
│       ├── loop.py             # main ReAct loop
│       ├── llm_client.py       # HTTP → Ollama
│       ├── parsing.py          # native / XML / fenced
│       ├── messages.py         # assistant/tool history
│       ├── prompts.py          # assembles the system prompt
│       ├── prompts/
│       │   ├── system.md
│       │   └── fenced_tools.md
│       ├── permissions.py      # bash/write/edit confirmation
│       ├── context.py          # history trim
│       ├── session.py          # ~/.ci2lab/sessions/
│       ├── repl.py             # interactive chat mode
│       ├── types.py            # AgentConfig, ToolCall, ToolResult
│       └── tools/
│           ├── registry.py     # schemas + dispatch + execute_tool
│           ├── bash.py
│           ├── filesystem.py   # ls, read_file, grep, glob, write_file, edit_file
│           └── paths.py        # resolve_path (sandbox)
├── docs/
│   ├── STRUCTURE.md
│   ├── HARDWARE_ROUTER_HANDOFF.md
│   └── audits/
│       └── current_harness_flow_audit.md   # this report
├── references/                 # extraction notes (not product code)
└── tests/                      # 12 harness tests
```

### 2.2 What has logic vs skeleton

| Path | Logic | Notes |
|------|-------|-------|
| `ci2lab/cli.py` | Yes | Full CLI: single turn, REPL, sessions, doctor |
| `ci2lab/pipeline.py` | Yes (partial) | Tries to import the router; falls back on `ImportError` |
| `ci2lab/contracts/types.py` | Yes | Shared types; `ModelSelection` consumed by the harness |
| `ci2lab/harness/**` | Yes | Complete harness |
| `ci2lab/hardware/` | No | `__init__.py` only |
| `ci2lab/router/` | No | `__init__.py` only |
| `ci2lab/runtime/` | No | `__init__.py` only |
| `ci2lab/config/` | — | Does not exist (mentioned in STRUCTURE.md) |
| `ci2lab/catalog/` | — | Does not exist (mentioned in STRUCTURE.md) |

---

## 3. Full execution flow

Example: `python -m ci2lab.cli "list the files"`

### Step by step

1. **Module invocation**
   `python -m ci2lab.cli` runs `ci2lab/cli.py` as `__main__` → calls `main()` → `sys.exit(main())`.

   Equivalent alternative: `python -m ci2lab` → `ci2lab/__main__.py` → `ci2lab.cli.main()`.

2. **Argument parsing** (`cli.main`)
   - positional `prompt` = `"list the files"`.
   - No subcommand → direct branch at lines 65–66.
   - Default flags: `--tool-mode native`, `--cwd` = absolute `os.getcwd()`, `--max-rounds 25`, `--yes` false, streaming on.
   - `--model` = `None` (resolved later).

3. **Session preparation** (`_resolve_selection` → `pipeline.prepare_session`)
   - Tries `from ci2lab.hardware.profiler import scan_hardware` etc. → **fails with `ImportError`**.
   - Fallback: `tag = force_model or os.environ.get("CI2LAB_MODEL", "llama3.1:8b")`.
   - Returns `(None, default_selection(tag, tool_mode))` → a `ModelSelection` with `backend_url=http://localhost:11434/v1`, `supports_tools=True`.

4. **Agent config** (`_build_config`)
   - `AgentConfig(cwd, max_rounds, auto_confirm=args.yes, stream=not args.no_stream, session_id)`.

5. **Turn execution** (`_run_turn` → `harness.run_agent`)
   - Prints model and CWD with Rich.
   - Enters the ReAct loop.

6. **Loop initialization** (`loop.run_agent`)
   - `LLMClient(selection)` → URL `http://localhost:11434/v1/chat/completions`.
   - `build_system_prompt(selection, cwd)` → reads `system.md` + an environment block + (optional) `fenced_tools.md`.
   - Initial history: `[system, user]`.
   - `tools = FUNCTION_SCHEMAS` if `selection.supports_tools`.

7. **Per round** (up to `max_rounds`):
   a. `trim_messages(history, selection.context_length)` — trims old history.
   b. `_call_llm(client, trimmed, tools, stream)` — streaming via Rich `Live` or `client.chat`.
   c. `resolve_tool_calls(content, llm_response.tool_calls, tool_mode, skip_fenced_if_native=True in native)`.
   d. **If no calls:** final answer → `append_assistant_turn` → save session → `break`.
   e. **If calls:** loop detection (same signature twice) → an unblock message or execution:
      - `append_assistant_turn(history, content, calls)`
      - For each call: `execute_tool(call, cfg)` in `registry.py`
      - `append_tool_results(history, results)`
      - Save session if `session_id` is set.

8. **`ls` tool execution** (typical case for "list the files"):
   - `check_permission("ls", …)` → direct allow (not in `CONFIRM_TOOLS`).
   - `_DISPATCH["ls"]` → `filesystem.ls(cfg.cwd, path=".")`
   - `resolve_path` confines paths to `cwd`.
   - Result truncated to `max_tool_output_chars` (10,000).
   - A `role: tool` message with `tool_call_id` is appended to the history.

9. **Next round**
   The model receives the history with assistant+tool_calls and results; generates a final text answer.

10. **Output to the user**
    - Streaming: live tokens; a final newline if there is text.
    - No streaming: prints `final_text`.
    - `run_agent` returns a `str`; the CLI returns exit code `0`.

---

## 4. Textual flow diagram

```text
User: python -m ci2lab.cli "list the files"
  ↓
ci2lab/cli.py::__main__  →  main(argv)
  ↓
argparse: prompt="list the files", cwd=abs(getcwd()), tool_mode=native, ...
  ↓
_resolve_selection(args, prompt)
  ↓
ci2lab/pipeline.py::prepare_session()
  ├─ try: hardware.profiler + router.resolve + runtime.ensure  → ImportError
  └─ except: default_selection(CI2LAB_MODEL | "llama3.1:8b")
  ↓
_build_config(args)  →  AgentConfig
  ↓
_run_turn(prompt, args)
  ↓
ci2lab/harness/loop.py::run_agent(user_prompt, selection, config)
  ├─ LLMClient(selection)
  ├─ build_system_prompt()  ← harness/prompts.py + prompts/*.md
  ├─ history = [system, user]
  └─ FOR round in 1..max_rounds:
       ├─ trim_messages(history, context_length)
       ├─ _call_llm()
       │    ├─ stream: LLMClient.stream_chat() → StreamToken* → LLMResponse
       │    └─ no-stream: LLMClient.chat()
       ├─ resolve_tool_calls()  ← harness/parsing.py
       │    ├─ native_to_tool_calls (priority)
       │    ├─ parse_xml_blocks
       │    └─ parse_fenced_blocks (unless native-only skip)
       ├─ if no calls → final answer → break
       └─ if calls:
            ├─ execute_tool()  ← harness/tools/registry.py
            │    ├─ check_permission()  ← harness/permissions.py
            │    └─ _DISPATCH[name](config, args)
            │         ├─ bash → tools/bash.py::run_bash
            │         └─ ls/read/grep/glob/write/edit → tools/filesystem.py
            └─ append_tool_results()  ← harness/messages.py
  ↓
final answer (str) + exit 0
```

**Alternative CLI flows:**

```text
ci2lab chat        → cli._run_repl → harness/repl.py::run_repl → run_agent per line
ci2lab agent "…"   → _run_turn (same flags in the subparser)
ci2lab sessions    → harness/session.py::list_sessions
ci2lab doctor      → httpx GET {CI2LAB_OLLAMA_URL}/api/tags
```

---

## 5. Important functions

| File | Function/class | Responsibility | Caller | Returns | Risks/notes |
|------|----------------|----------------|--------|---------|-------------|
| `cli.py` | `main()` | CLI entry, subcommand routing | `__main__.py`, `ci2lab` entrypoint | `int` exit code | `--cwd` exists; no `--workspace` |
| `cli.py` | `_run_turn()` | One agent turn | `main()` | exit code | Only catches `KeyboardInterrupt` |
| `cli.py` | `_resolve_selection()` | Gets a `ModelSelection` | `_run_turn`, `_run_repl` | `ModelSelection` | Always falls back without the router |
| `cli.py` | `_cmd_doctor()` | Health check for package + Ollama | `main()` | 0/1 | Base URL without `/v1` (correct for `/api/tags`) |
| `pipeline.py` | `prepare_session()` | Router↔harness integration | CLI | `(HardwareProfile\|None, ModelSelection)` | `pull` ignored in the fallback |
| `harness/__init__.py` | `default_selection()` | Test ModelSelection | `pipeline` fallback | `ModelSelection` | Default `llama3.1:8b` |
| `harness/loop.py` | `run_agent()` | Full ReAct loop | CLI, REPL | final `str` | LLM error → generic message, does not re-raise |
| `harness/loop.py` | `_call_llm()` | Streaming or sync chat | `run_agent` | `LLMResponse` | If stream has no final LLMResponse, uses the buffer |
| `harness/llm_client.py` | `LLMClient` | OpenAI-compatible HTTP | `run_agent` | — | A new `httpx.Client` per call |
| `harness/llm_client.py` | `chat()` / `stream_chat()` | POST chat/completions | `_call_llm` | `LLMResponse` / iterator | `raise_for_status()` without a friendly message |
| `harness/parsing.py` | `resolve_tool_calls()` | Orchestrates parsers | `run_agent` | `list[ToolCall]` | In native, fenced ignored if `tool_calls=[]` |
| `harness/parsing.py` | `native_to_tool_calls()` | Normalizes the native API | `resolve_tool_calls` | `list[ToolCall]` | Filters names not in `TOOL_NAMES` |
| `harness/messages.py` | `append_assistant_turn()` | Appends assistant (+ tool_calls) | `run_agent` | `None` | Serializes args as a JSON string |
| `harness/messages.py` | `append_tool_results()` | Appends `role: tool` messages | `run_agent` | `None` | `tool_call_id` required by the API |
| `harness/prompts.py` | `build_system_prompt()` | Dynamic system prompt | `run_agent` | `str` | Reads `.md` from the filesystem |
| `harness/context.py` | `trim_messages()` | Trim by estimated tokens | `run_agent` | `list[dict]` | ~4 chars/token estimate, coarse |
| `harness/permissions.py` | `check_permission()` | Confirmation gate | `execute_tool` | `(bool, str\|None)` | Only bash/write/edit |
| `harness/tools/registry.py` | `execute_tool()` | Dispatch + permissions + truncation | `run_agent` | `ToolResult` | `Exception` → string to the model |
| `harness/tools/registry.py` | `FUNCTION_SCHEMAS` | OpenAI tool schemas | `run_agent` → LLM | `list[dict]` | Includes write/edit even though the roadmap said future |
| `harness/tools/paths.py` | `resolve_path()` | Path sandbox | filesystem tools | `Path` | `PathViolationError` not typed in the registry |
| `harness/tools/bash.py` | `run_bash()` | subprocess shell | `execute_tool` | `str` | `shell=True`, no blocklist |
| `harness/tools/filesystem.py` | `ls`, `read_file`, etc. | Confined I/O | `execute_tool` | `str` | `grep` uses `rg` if available |
| `harness/session.py` | `save_session()` | JSON persistence | `run_agent`, REPL | `Path` | Only if `session_id` is set |
| `harness/repl.py` | `run_repl()` | Interactive loop | CLI `chat` | `None` | Auto-assigns `session_id` |
| `contracts/types.py` | `ModelSelection` | Router→harness contract | The whole harness | dataclass | **Actively integrated** |

---

## 6. Current tools

| Tool | File | Parameters | Permission required | What it does | Risks |
|------|------|------------|---------------------|--------------|-------|
| `bash` | `tools/bash.py` | `command` (string) | **Confirmation** (`CONFIRM_TOOLS`) or `--yes` | `subprocess.run(command, shell=True, cwd=cwd, timeout=60s)` | Arbitrary shell execution; no blocklist (`rm -rf`, `curl \| sh`, etc.) |
| `read_file` | `tools/filesystem.py` | `path`, `offset?`, `limit?` | Allow | Reads a UTF-8 file, numbered lines, ~2000 lines max | Path sandbox via `resolve_path`; binary files as text |
| `ls` | `tools/filesystem.py` | `path?` (default `.`) | Allow | Lists a dir (hides dotfiles) | Only inside `cwd` |
| `grep` | `tools/filesystem.py` | `pattern`, `path?`, `glob?`, `ignore_case?`, `max_results?` | Allow | `rg` if available; Python `rglob` fallback | Fallback may be slow on large repos; ignores `.gitignore` in the fallback |
| `glob` | `tools/filesystem.py` | `pattern`, `path?` | Allow | `Path.glob`, max 100 results | Broad patterns can be costly |
| `write_file` | `tools/filesystem.py` | `path`, `content` | **Confirmation** | Creates dirs and overwrites a file | Already working; can destroy files after confirmation |
| `edit_file` | `tools/filesystem.py` | `path`, `old_string`, `new_string`, `replace_all?` | **Confirmation** | Exact text replacement | Already working; partial replacement may fail if `old_string` is ambiguous |

**Central registry:** schemas and dispatch in `harness/tools/registry.py`.
**Alias names in parsing:** `shell`→`bash`, `read`→`read_file`, `write`→`write_file`, `edit`→`edit_file`.

---

## 7. Permission flow

### Where the confirmation is decided

1. `registry.execute_tool()` calls `check_permission(name, permission_summary(name, args), auto_confirm=config.auto_confirm, confirm_callback=config.confirm_callback)`.
2. `permissions.CONFIRM_TOOLS = {"bash", "write_file", "edit_file"}`.
3. If the tool is **not** in the set → immediate `(True, None)`.
4. If `auto_confirm=True` (CLI flag `--yes`) → allow without asking.
5. Otherwise → `default_confirm()` does `input("[s/N]")`; valid answers: `s`, `si`, `sí`, `y`, `yes`.
6. If denied → a `ToolResult` with an error returned to the model (not an exception).

### How `--yes` works

- CLI: `--yes` → `AgentConfig.auto_confirm=True`.
- Affects only tools in `CONFIRM_TOOLS`.
- Does **not** disable the path sandbox or limit bash commands.

### Can `bash` run without permission by accident?

| Scenario | Does bash run? |
|----------|----------------|
| User answers `n`/Enter at the prompt | No — error to the model |
| User uses `--yes` | Yes — intentional |
| Tool is not `bash` | N/A |
| Model calls `bash` via fenced in `native` mode with `tool_calls=[]` | **No** — fenced ignored (see §10) |
| `read_file`/`ls`/`grep`/`glob` | Yes — no confirmation (read-only) |

**Residual risk:** `write_file`/`edit_file` require confirmation but **are already implemented**. A model can request a write; if the user confirms (`s` or `--yes`), the disk is modified.

### Dangerous commands not blocked

There is no blocklist or allowlist in `bash.py`. Any approved command runs with the user's privileges in `cwd`, including:

- Data destruction (`rm`, `del`, reformatting)
- Exfiltration (`curl`, `scp`, reading `~/.ssh`)
- Modifying git history, installing packages, fork bombs, etc.

The only current mitigation is the **interactive confirmation** for `bash` (and write/edit).

---

## 8. Prompt flow

### Where the system prompt is

- Base template: `ci2lab/harness/prompts/system.md`
- Assembly: `ci2lab/harness/prompts.py::build_system_prompt()`

### How tool snippets are loaded

- `_read("system.md")` always.
- A dynamic `## Environment` block (cwd, date, model, OS).
- `fenced_tools.md` **only if** `tool_mode == "fenced"` **or** `not selection.supports_tools`.
- In `native` mode with `supports_tools=True` (the default case): `fenced_tools.md` is **not** included.

### What is sent to the model

Per round, in the POST to Ollama:

```json
{
  "model": "<ollama_tag>",
  "messages": [ /* system, user, assistant, tool, ... */ ],
  "temperature": 0.2,
  "max_tokens": 4096,
  "stream": true|false,
  "tools": [ /* FUNCTION_SCHEMAS — only if native + supports_tools */ ]
}
```

The system prompt describes the 7 tools in a Markdown table plus usage rules, but does **not** include fenced examples in native mode.

### Prompt ↔ tools alignment

| Aspect | Status |
|--------|--------|
| Tools listed in `system.md` | Matches `TOOL_NAMES` / schemas |
| Instruction to use tools before answering | Present |
| Fenced format documented for the model | Only in fenced mode |
| Native function calling | Schemas sent via API; the prompt does not explain the tool JSON format |

### What can prevent correct tool use

1. **A model without reliable function calling** in Ollama → text-only responses, no `tool_calls`.
2. **Native mode + `tool_calls=[]`**: fences in the content are **not parsed** (see §10) → the agent may "say" it listed files without running `ls`.
3. **Default model `llama3.1:8b`** can behave differently from `qwen2.5-coder:7b` on tool use.
4. **Spanish prompt**, English schemas — usually works, but small models may ignore tools.
5. **No explicit message** in the system prompt saying "you must use function calling, do not simulate results."
6. **Anti-loop** can inject "stop repeating the tool" and force an answer with no real evidence.

---

## 9. LLM client and communication with Ollama

### How Ollama is called

- `LLMClient` class in `harness/llm_client.py`.
- URL: `{selection.backend_url}/chat/completions` → default `http://localhost:11434/v1/chat/completions`.
- Client: synchronous `httpx`, 300 s timeout.

### Payload

See §8. Tools in the payload only when:

```python
tools and selection.supports_tools and selection.tool_mode == "native"
```

### Response parsing

- No-stream: `data["choices"][0]` → `message.content` + `message.tool_calls`.
- Stream: SSE `data: {...}`; accumulates `delta.content` and `delta.tool_calls` per index; emits `StreamToken` and finally `LLMResponse`.

### Error handling

| Error | Current behavior |
|-------|------------------|
| Connection refused (Ollama off) | `httpx` exception → caught in `run_agent` → a red "Error contacting the model: …" printed; returns that string |
| HTTP 4xx/5xx | `raise_for_status()` → same generic capture |
| Invalid JSON in stream | Chunk ignored (`continue`) |
| Nonexistent model | Ollama HTTP error (typically 404/500) → generic message |
| Timeout | httpx exception → generic message |

**There is no:** retry, "is Ollama running?" diagnostic, `ollama serve` suggestion, or distinction between model-not-found and connection-refused in the loop (only `doctor` checks that separately).

### Environment variables

| Variable | Use |
|----------|-----|
| `CI2LAB_MODEL` | Default Ollama tag in the fallback |
| `CI2LAB_OLLAMA_URL` | Only in `doctor` (base `http://localhost:11434`, without `/v1`) |

`ModelSelection.backend_url` is not overridden from env in the current fallback.

---

## 10. Tool-call parsing

### Resolution order (`resolve_tool_calls`)

1. **Native:** if `native_calls` is truthy → `native_to_tool_calls()`; if it produces calls, return.
2. **XML:** `parse_xml_blocks()` — `<tool_call>`, `<invoke name="…"><parameter>`, normalized DSML.
3. **Skip fenced:** if `tool_mode=="native"` and `native_calls is not None` → return `[]`.
4. **Fenced:** `parse_fenced_blocks()` — `` ```tool_name\n...\n``` ``.

### Supported formats

| Format | Function | Example |
|--------|----------|---------|
| OpenAI/Ollama native | `native_to_tool_calls` | `tool_calls[].function.name/arguments` |
| Fenced | `parse_fenced_blocks` | `` ```ls\n.\n``` `` |
| XML invoke | `parse_xml_blocks` | `<invoke name="bash">…` |
| DSML (DeepSeek) | `_normalize_dsml` + XML | Variants with unicode pipes |

### Important limitations

1. **Native-mode fenced suppression:** `llm_response.tool_calls` is always a `list` (never `None`). In native, if the model returns `[]` but writes fences in `content`, **tools are not run** (step 3 returns `[]`).
2. **Unknown names** in native are silently dropped.
3. **`parse_arguments` fallback:** invalid JSON in native → `{"command": raw}` (bias toward bash).
4. **`strip_tool_markup`:** cleans fences/XML from the text shown to the user.
5. **Schemas include write/edit** but the product roadmap treats them as future — the parser already supports them.

---

## 11. Packaging and CLI execution

### `python -m ci2lab.cli`

Verified: shows the argparse help.

### `python -m ci2lab`

Verified: `__main__.py` → `cli.main()`, same help.

### `ci2lab` entrypoint

Declared in `pyproject.toml`:

```toml
[project.scripts]
ci2lab = "ci2lab.cli:main"
```

Correct. In the audit environment the package was **not installed** (`pip show ci2lab` → not found); after `pip install -e .` the `ci2lab` command would be available.

### `.md` prompts in the package

```toml
[tool.hatch.build.targets.wheel.force-include]
"ci2lab/harness/prompts" = "ci2lab/harness/prompts"
```

Includes the directory in the wheel. In an editable install, `prompts.py` resolves via `Path(__file__).parent / "prompts"` — it works.

### Runtime dependencies

`httpx`, `psutil`, `rich` (psutil not yet used by the harness at the time; reserved for the future hardware profiler).

---

## 12. What is already done

- **MVP migration** of the harness into the `IAmultiagentica` product repo.
- **Working CLI** with a positional shortcut, and the `agent`, `chat`, `sessions`, `doctor` subcommands.
- **ReAct harness** complete: multi-round, Rich streaming, anti-loop, context trim.
- **Tools:** `bash`, `read_file`, `ls`, `grep`, `glob`, `write_file`, `edit_file` (the last two already in code).
- **Confirmation** for `bash`, `write_file`, `edit_file`; the `--yes` flag.
- **Ollama client** via httpx (OpenAI-compatible API).
- **Parsing** of multiple formats (native, XML, fenced).
- **Path sandbox** (`resolve_path`) for the filesystem tools.
- **Persistent sessions** under `~/.ci2lab/sessions/` (REPL + `--session`).
- **`ModelSelection` contract** integrated between pipeline and harness.
- **README** and structure/handoff docs.
- **Tests:** 12 automated tests covering the loop, parsing, tools, context, sessions.

---

## 13. What is left to do

### High priority

| Item | Current state |
|------|---------------|
| `config.py` | Did not exist; all config via CLI flags + scattered env |
| `ci2lab.yaml` | Did not exist |
| `--workspace` | Did not exist; partial equivalent: `--cwd` |
| Path validation | Partial (`resolve_path`); `PathViolationError` not surfaced to the user |
| Clear errors if Ollama fails | Generic in the loop; only `doctor` gives a diagnostic |
| Align the default model | Code: `llama3.1:8b`; desired operation: `qwen2.5-coder:7b` |

### Medium priority

| Item | Current state |
|------|---------------|
| `run_logger.py` | Did not exist; Rich prints only |
| `grep` / `glob` | **Already implemented** in `filesystem.py`; needs maturing (dedicated tests, `.gitignore` in the fallback) |
| Manual/automated tests | 12 unit tests; no integration with real Ollama |

### Future priority

| Item | Current state |
|------|---------------|
| ~~`write_file` / `edit_file`~~ | **Superseded** — supervised mode with diff preview; see [`WRITE_POLICY.md`](../WRITE_POLICY.md) |
| ~~Diff preview~~ | **Superseded** — `write_preview.py`, evals `005`–`007` |
| Git snapshot / rollback | Does not exist |

### Out of scope at the time

- Multi-model routing (real `hardware/`, `router/`, `runtime/`)
- Hardware profiler
- External wrappers / MCP / UI
- The `models.json` catalog (the `catalog/` folder not yet created)

---

## 14. Current risks

### Security

- **`bash` with `shell=True`** and no blocklist: high risk if the user confirms or uses `--yes`.
- **`write_file`/`edit_file` working** despite a "future" roadmap: risk of disk modification after confirmation.
- **stdin confirmation** is vulnerable in non-interactive pipelines (EOF → deny, which is correct).

### Paths

- The `resolve_path` sandbox is solid against direct path traversal.
- **Symlinks** outside the workspace: there is no explicit check after `resolve()`; a symlink inside `cwd` could point outside.
- **`PathViolationError`** turns into a generic `"Error: …"` via the broad except in `execute_tool`.

### Permissions

- Only 3 tools are gated; free reads include any file under `cwd`.
- `--yes` cancels all write and shell confirmation.

### Unhandled errors / UX

- Ollama failure mid-task: a red message, no hint about `ci2lab doctor` or `ollama serve`.
- A model without tool support can hallucinate results (especially with fenced suppressed in native).
- Streaming + empty tool_calls: hard to debug without structured logs.

### cwd dependency

- Default `os.getcwd()` — running from the wrong directory changes the sandbox.
- Sessions store `cwd` but there is no validation on resume.

### Imports and packaging

- `pipeline` imports future modules inside `try/except ImportError` — safe.
- `docs/STRUCTURE.md` references nonexistent `catalog/` and `config/` — confusing for new devs.

### Experience if Ollama is not running

- Single turn: `"Error contacting the model: [ConnectError…]"` and exit 0 (not an error exit).
- `doctor` does return exit 1.

---

## 15. Recommended next steps

Suggested order for whoever continues the development (not implemented in this audit):

1. **Centralized config** (`config.py` + `ci2lab.yaml`): default model `qwen2.5-coder:7b`, Ollama URL, cwd/workspace, default flags.
2. **Actionable Ollama errors** in `run_agent` / `LLMClient`: distinguish connection, HTTP, missing model; suggest `ci2lab doctor`; consider a non-zero exit code.
3. **Revisit the fenced policy in native**: pass `native_calls=None` when the list is empty, or try fenced as a fallback if native produced no calls.
4. **`--workspace` alias** of `--cwd` + clear sandbox documentation.
5. **A minimal bash blocklist** (or `shell=False` mode with limited splitting) — design before code.
6. **An explicit decision on write/edit**: disable dispatch until the UX is ready, or document as beta with confirmation.
7. **`run_logger.py`** for per-round JSON traces (prompt, tools, latency, errors).
8. **Integration tests** optionally with a mock HTTP Ollama.
9. **Implement router/hardware/runtime** when moving beyond the single-model MVP (out of immediate scope).

---

## Appendix: map of critical imports

```text
cli.py
  → pipeline.prepare_session
  → harness.run_agent, harness.repl.run_repl, harness.session.list_sessions

pipeline.py
  → contracts.types (HardwareProfile, ModelSelection)
  → harness.default_selection

harness/loop.py
  → contracts.types (ModelSelection, HardwareProfile)
  → harness.llm_client, messages, parsing, prompts, session, tools.registry, types

harness/llm_client.py
  → contracts.types.ModelSelection

harness/tools/registry.py
  → harness.tools.bash, filesystem, permissions, types
```

This map summarizes **which file calls which** on the critical path CLI → agent response.

---

## 16. Update — cleanup phase

**Date:** 2026-06-09

Changes applied without altering the ReAct architecture or implementing router/hardware/runtime.

### Implemented

| Task | Files | Notes |
|------|-------|-------|
| `config.py` + `ci2lab.yaml` | `ci2lab/config.py` | Precedence CLI > env > yaml > defaults; minimal YAML parser, no deps |
| `--workspace` | `ci2lab/cli.py` | Alias of `--cwd`; error if both |
| `bash` blocklist | `harness/tools/bash_safety.py` | Applied before confirmation and with `--yes` |
| Ollama errors | `harness/llm_errors.py`, `llm_client.py`, `loop.py`, `cli.py` | `LLMConnectionError` (exit 2), `LLMModelNotFoundError` (exit 3) |
| Fenced/native fallback | `harness/parsing.py` | Empty native list → XML/fenced |
| `write_file` / `edit_file` | — | Supervised mode — `WRITE_POLICY.md`, `write_edit_tools_status.md` |

### Default model

It stays **`llama3.1:8b`**. Not migrated to Qwen in this phase.

### Configuration

Files searched: `./ci2lab.yaml`, `./ci2lab.yml`, `./ci2lab.json`, `~/.ci2lab/ci2lab.yaml`, or the path in `CI2LAB_CONFIG`.

Environment variables: `CI2LAB_MODEL`, `CI2LAB_OLLAMA_URL`, `CI2LAB_BACKEND_URL`, `CI2LAB_TOOL_MODE`, `CI2LAB_MAX_ROUNDS`, `CI2LAB_WORKSPACE` / `CI2LAB_CWD`, `CI2LAB_STREAM`, `CI2LAB_YES` / `CI2LAB_AUTO_CONFIRM`.

### Pending after cleanup (partially superseded in later phases)

- ~~Diff preview~~ → implemented (see `write_edit_tools_status.md`)
- Git rollback — pending
- Router, hardware profiler, MCP, UI — pending

---

## 17. Update — structured logging (`runs/`)

**Date:** 2026-06-09

| Component | Status |
|-----------|--------|
| `harness/run_logger.py` | Done |
| Per-run artifacts | `run_summary.json`, `conversation.json`, `tool_calls.jsonl`, `final_answer.md`, `config_snapshot.json` |
| CLI `--runs-dir`, `--no-log` | Done |
| Default logging on | In `runs/` |
| Log failures do not break the agent | Yellow warning |
| Documentation | [`run_logging.md`](run_logging.md), [`manual_tests.md`](../manual_tests.md) |

Full detail in [`docs/audits/run_logging.md`](run_logging.md).

---

## 18. Milestone close — mock/live validation

**Date:** 2026-06-09

| Deliverable | Status |
|-------------|--------|
| Mock evals 7/7 | Done |
| Live evals 7/7 (`llama3.1:8b`) | Done |
| `pytest` | 64 passed |
| `ci2lab/evals/` | mock/live runner |
| Write/edit diff preview | Done |
| `run_logger.py` + `runs/` | Done |
| `config.py` + `ci2lab.yaml` | Done |

**Closing documents:** [`live_eval_status.md`](live_eval_status.md), [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md), [`regression_checklist.md`](../regression_checklist.md).

**Decision:** the agentic harness stands as a validated functional base; hardware/router/runtime are the next product phase, not this milestone.
