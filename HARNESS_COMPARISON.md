# Harness comparison: ci2lab vs. Claude Code (leaked source)

**Date:** 2026-07-09 · **ci2lab at:** commit `02bf780` (HEAD) · **Claude Code at:** `../claude-code-main` (leaked source, README dates the leak 2026-03-31)

This document compares the two agent harnesses along five axes: overall structure, the core agent loop, the techniques each uses (tools, prompting, context, multi-agent, security), the effectiveness evidence available for each, and concrete improvements for both. File references use `path:line` as found on disk; Claude Code paths are relative to `claude-code-main/`, ci2lab paths relative to this repo.

**Provenance caveats.** The Claude Code tree is a third-party repackaging of a leak: the top-level `prompts/00-16-*.md` are community-written *rebuild instructions*, and `docs/*.md` are community-written and partly aspirational (they drift from the source, e.g. renamed tools). Everything cited here comes from `src/**` itself, which is internally consistent and almost certainly authentic. It is the **external build variant** — many `USER_TYPE === 'ant'` (Anthropic-internal) branches exist in source but are compiled out for external users, and several subsystems (coordinator, proactive mode, workflows) are behind build-time feature flags. Statements about Claude Code's *behavior* therefore describe what the code does, not necessarily what every shipped build enables.

---

## 1. At a glance

| | **Claude Code** | **ci2lab** |
|---|---|---|
| Language / runtime | TypeScript on Bun; React + Ink terminal UI | Python 3.11+; Rich terminal UI + local web UI |
| Size | ~1,940 source files, ~512K lines | One package (`ci2lab/`), ~905 tests |
| Model assumption | Frontier hosted models (Anthropic API; Bedrock/Vertex) | Local open-weight models (Ollama native, any OpenAI-compatible server) |
| Model selection | User picks from Claude family; per-model prompt tweaks | **Hardware profiling → router recommends from an 86-model catalog**, context window auto-capped to VRAM/RAM (`ci2lab/router/selection.py`) |
| Tool calling | Native `tool_use` blocks only; Zod-validated | Native **plus five lenient text parsers** (XML, fenced, bare JSON, name+JSON, generic fences) |
| Tool count | ~40 (many feature-gated), plus MCP | 32 (`schemas_parts/registry.py:12-48`), plus MCP |
| Loop bound | Unbounded (optional `maxTurns`) | Hard cap 25 rounds (`harness/types.py:43`) |
| Tool execution | Read-only batches run in parallel (cap 10) | Strictly sequential |
| Context strategy | Cache-preservation economics: snip → microcompact → collapse → autocompact | Small-window survival: prune reads → micro-compact @65% → LLM summary @80% |
| Trajectory guards | Prompt text + circuit breakers; no repetition detector | 11 bounded nudges, loop detection, retry governor, deterministic grounding gates |
| Permissions | Modes incl. ML classifier "auto" mode; rules; hooks; OS sandbox | Three switchable engines (one modeled on Claude Code's); hard guards; audit trail |
| Multi-agent | `Task` tool: parallel in-process subagents, teams, background tasks | Separate orchestrator: fixed phase pipeline with deterministic checkpoints |
| Experimentation | GrowthBook A/B flags + OpenTelemetry in production | Benchmark suite (pass@k, cost, false-positive metric) + ~905 CI tests |

The one-sentence version: **Claude Code invests its robustness budget in infrastructure and behavioral prompt-steering because it can trust the model; ci2lab invests it in tolerant input handling and deterministic guardrails because it cannot.** Nearly every design divergence traces back to that difference in model assumption — and, secondarily, to opposite economics (paid API tokens at scale vs. free-but-small local context).

---

## 2. General structure

### 2.1 Claude Code

```
User input → CLI parser (Commander) → REPL (React/Ink)
  → query() loop (src/query.ts)                        ← the engine
      → system prompt assembly (src/constants/prompts.ts)
      → context pipeline: snip → microcompact → collapse → autocompact
      → Anthropic API (src/services/api/claude.ts, withRetry.ts)
      → tool orchestration (src/services/tools/toolOrchestration.ts)
          → permissions (src/utils/permissions/) → hooks → tool.call()
      → attachments / system-reminders (src/utils/attachments.ts)
```

It is a **product monolith**: the engine sits inside a full application with ~140 UI components, a services layer (analytics, OAuth, MCP, plugins, session memory, cost tracking), an SDK entrypoint, an IDE bridge, and remote/teleport modes. Variants are managed by build-time dead-code elimination (`bun:bundle` `feature()` flags) and runtime A/B flags (GrowthBook). The core loop is a hand-written async generator (`src/query.ts:241`), not a framework: one `while (true)` carrying a typed `State` with explicit transition reasons (`next_turn`, `reactive_compact_retry`, `max_output_tokens_recovery`, …).

### 2.2 ci2lab

```
cli / ui → config (ci2lab.yaml, env, CLI) → pipeline.prepare_session()
  → hardware profile + router → ModelSelection (model, context cap, tool_mode)
  → pipeline.build_agent_config() → AgentConfig
  → harness.query.run_agent() (loop.py)                ← the engine
      → backends (Ollama native /api/chat | OpenAI-compat)  [pluggable transport]
      → tools: parse (5 parsers) → dispatch → security gate → execute
      → context: prune / micro-compact / summarize
      → nudges, retry governor, verifier, grounding review
  (separate entry: harness.multiagent.run_multi_agent — phase orchestrator)
```

It is a **layered research instrument**: contracts (`contracts/types.py`) separate router from harness; transports are pluggable behind `LLMBackend` (`harness/backends/`); tool declarations live in four registries cross-checked by a consistency test (`tests/test_tool_registry_consistency.py`); the whole package is mypy-clean with a growing strict subset. Two things exist here that have **no Claude Code equivalent at all**: the hardware-profiling router (Claude Code never has to decide *which* model fits in memory) and the backend abstraction (Claude Code speaks only the Anthropic API shape, with Bedrock/Vertex as auth/endpoint variants of it).

### 2.3 Reading the difference

Both converge on the same canonical skeleton — system prompt + tool registry + LLM call + parse + permission gate + execute + feed back + compaction — which is worth noting as convergent evolution, since ci2lab did not copy this structure from the leak (several ci2lab docstrings cite frontier harnesses as *behavioral* models, and `security/engine.py` explicitly names a `claude_experimental` engine, but the loop mechanics are original). The structural differences that matter:

1. **Where variation lives.** Claude Code varies by build flags and A/B gates inside one codebase; ci2lab varies by configuration seams (backend, model, security engine, tool mode). Claude Code's approach suits a product shipping to millions; ci2lab's suits controlled experiments — you can hold everything constant and swap one seam, which is exactly what its benchmark methodology (H2/H3) needs.
2. **Engine coupling.** Claude Code's engine is extractable in principle (the SDK entrypoint proves it) but is entangled with services (analytics, policy limits, GrowthBook) that the leak's own rebuild notes describe stubbing. ci2lab's `run_agent` is callable with a config object and a transport, nothing else.
3. **UI as architecture.** In Claude Code the UI is load-bearing: permission dialogs, plan mode, background-task pills, and queued-message steering are part of the agent's control loop. ci2lab's loop is headless-first with Rich rendering layered on; its web UI drives the same `run_agent`.

---

## 3. The core agent loop

| Mechanism | Claude Code | ci2lab |
|---|---|---|
| Loop form | `while(true)` generator, state machine with named transitions (`src/query.ts:241,307`) | `for round_num in range(1, max_rounds+1)` (`loop.py:1001`) |
| Iteration bound | None built-in; optional `maxTurns` (`query.ts:1705`) | 25 rounds; subagents 5–15 (`multiagent/runner.py:22-43`) |
| Turn detection | Presence of `tool_use` blocks — `stop_reason` explicitly distrusted (`query.ts:554,829-834`) | Parse result of `resolve_tool_calls` over content + native calls (`loop.py:1083`) |
| Streaming | Always streams; can execute tools **mid-stream** as blocks complete (`StreamingToolExecutor`, `query.ts:562-568,842`) | Streaming **disabled whenever tools are available** (`stream_this_round = cfg.stream and not bool(tools)`, `loop.py:1039`); only the final tool-free answer streams |
| Parallel tools | Consecutive read-only calls batched, up to 10 concurrent (`toolOrchestration.ts:8-12,91-116`) | Sequential, in model order; mutating calls after an earlier same-batch error are skipped (`_SKIPPED_AFTER_ERROR`, `loop.py:1411-1420`) |
| Tool errors | `<tool_use_error>` result fed back; model self-corrects | `Error:`-prefixed `ToolResult` fed back; harness also *accounts* for it (governor, streaks, ledger) |
| Orphan safety | Synthesizes `is_error` results for any `tool_use` without a result on abort/fallback (`query.ts:123-149`) | Not needed — text-first protocol has no orphan invariant |
| Thinking | Interleaved thinking beta; thinking-block preservation invariants documented in-code (`query.ts:151-163`) | None (local models; reasoning happens in visible text) |
| End of turn | Stop hooks may block completion and re-drive the loop (`query/stopHooks.ts:65`) | Finish-guards: verifier, grounding review, todo/write-intent nudges may re-drive the round |

Two design decisions deserve explanation:

- **Claude Code streams aggressively; ci2lab refuses to.** Claude Code's UX depends on tokens appearing instantly, and with a strong model, provisional text before tool calls is rare and harmless. ci2lab inverts this: weak models routinely emit half-formed tool syntax mixed with prose, so the loop parses first and renders only what survives `strip_tool_markup` — trading perceived latency for never showing the user hallucinated tool output. Since ci2lab also executes sequentially, a local multi-tool round pays full serialization cost; Claude Code overlaps execution with generation.

- **Claude Code has no iteration cap and no repetition detector.** This is the single clearest statement of trust in the model. Its protections are infrastructural: API retry budget (10, exponential backoff + jitter, `withRetry.ts:52-55,530-548`), 529-fallback to a secondary model, autocompact circuit breaker (3 failures), max-output-token recovery (3 attempts with an explicit "resume directly, no apology" nudge, `query.ts:164,1223-1229`), and a token-budget diminishing-returns stop. Nothing watches whether the *model* is going in circles — the system prompt just says not to. ci2lab, by contrast, hashes every round's tool-call signature into a 6-deep deque, nudges at 2 repeats, aborts after 3 nudges (`loop.py:117,932,1350-1381`), and separately budgets exact-call retries (2) and error-class retries (3) in the retry governor (`retry_governor.py:24-25`) — with the deliberate carve-out that `command_failed` (a red test) never counts, because re-running a failing check while fixing it is correct behavior (`loop.py:1509,1522`).

---

## 4. Tool systems

### 4.1 Definition and registration

**Claude Code** defines each tool as an object implementing a rich interface (`src/Tool.ts:362-695`) with **fail-closed defaults** (`TOOL_DEFAULTS`, `Tool.ts:757-769`): a tool that declares nothing is not concurrency-safe, not read-only, not destructive. Beyond schema and execution, the interface carries product concerns — six render methods, permission matchers, an auto-classifier input, deferred-loading hints. Tool *descriptions are prompt engineering artifacts*: `BashTool`'s prompt is a multi-section document with a git-safety protocol, commit/PR workflow with heredoc examples, and a dynamically generated sandbox section (`src/tools/BashTool/prompt.ts:42-369`). Registration is code + feature gates (`src/tools.ts:193-251`), with MCP tools merged in and name collisions resolved in favor of built-ins, each partition **sorted for prompt-cache stability** (`tools.ts:345-367`).

**ci2lab** declares each tool in four places — canonical name set, JSON schema, dispatch table, capability set — and enforces their agreement with a dedicated test (`tests/test_tool_registry_consistency.py`) plus a module-load assertion (`capabilities.py:80-82`). Capabilities (read-only / file-write / mutating) are a single source of truth imported by the loop, the roles system, and the evidence ledger, so steering logic can never disagree with execution. There is no per-tool prompt document; usage guidance is centralized in `system.md` (tools table, argument names, "choosing the right tool").

The trade-off: Claude Code's per-tool prompts let each tool teach its own idioms at the cost of thousands of system-prompt tokens (affordable at 200K–1M context); ci2lab's centralized terse catalog fits an 8K–32K window but gives the model less per-tool guidance — one reason it needs the nudge layer.

### 4.2 Parsing: the biggest single divergence

Claude Code accepts **only** native `tool_use` blocks, Zod-validates them, and feeds validation failures back as `<tool_use_error>` messages for the model to fix (`toolExecution.ts:615-680`). It never repairs model output.

ci2lab runs native calls first, then five text parsers in priority order (`parsing_parts/resolver.py:116-127`), with JSON escape repair (`repair_invalid_json_escapes` doubles invalid backslashes so `"ERR-\d{4}"` survives, `common.py:78-86`), tool-name aliasing (`shell→bash`, `find→glob`, `common.py:14-52`), and tool inference from bare argument shapes (`old_string`+`new_string` → `edit_file`, `common.py:185`). If something *looked* like a tool attempt but nothing parsed, a bounded hint teaches the correct syntax (`loop.py:1128-1147`).

This is the correct split given each harness's model population: Anthropic post-trains its models on its own tool schema, so leniency would only mask regressions; local 7B–32B models emit malformed calls constantly, so strictness would mean near-zero task completion. The subtle cost on ci2lab's side is that five parsers over free text can misfire (e.g., a generic ```bash fence in *quoted documentation* could be parsed as a call) — the harness mitigates with ordering and the `_parse_generic_fenced_blocks` last-resort position, but the risk is structural.

### 4.3 Edit safety and file handling

Both enforce `old_string` uniqueness with a count-and-refuse (`FileEditTool.ts:329-343`; `write_preview.py:127-133`). Claude Code goes two steps further: **read-before-edit** is a hard validation gate backed by a `readFileState` cache populated by Read (`FileEditTool.ts:275-287`), and **staleness detection** compares file mtime against the recorded read time, re-checked atomically inside the write (`FileEditTool.ts:290-311,451-468`). ci2lab has only a *hint* ("Call read_file with the exact path before editing", `tools/file_hints.py:21-32`) plus a loop-level heuristic that prepends a read when the user asked for one (`_prepend_missing_reads`, `loop.py:684`) — a real gap; see §7.

Large outputs: both offload to disk rather than truncate, telling the model where the full result lives (Claude Code `<persisted-output>` above 50K chars with a 200K per-message aggregate budget, `toolLimits.ts:13,49`; ci2lab head+tail preview above 10K chars with "saved to `path`, read it with read_file", `output_offload.py:29-78`). Claude Code additionally hard-caps Read at 25K tokens/256KB pre-flight (`FileReadTool/limits.ts`).

### 4.4 Bash

Claude Code treats Bash as a security surface: per-subcommand permission matching (so `ls && git push` triggers a `Bash(git *)` rule, `BashTool.tsx:445-468`), command-injection detection (command substitution, backticks, heredoc verification — `bashSecurity.ts`, 102KB), allowlist-based read-only classification so safe commands can parallelize (`readOnlyValidation.ts`), and OS sandboxing (macOS Seatbelt / Linux bubblewrap via `@anthropic-ai/sandbox-runtime`).

ci2lab treats Bash as a *fallback to be redirected*: `bash cat file` is rewritten into the real `read_file` tool (`executor_parts/core.py:135-147`), a regex blocklist stops catastrophic commands (`bash_safety.py:11-53`), path confinement applies inside command text, and — the benchmark-driven refinement — non-zero exit codes are prefixed `Error: command exited with code N` **while keeping full stdout/stderr**, classified as `command_failed`, and exempted from retry budgets (`tools/bash.py:73-86`, `security/policy.py:108-112`). Claude Code has no equivalent of that observed-failure/pipeline-failure distinction because it has no retry accounting to feed.

---

## 5. Prompting and steering techniques

### 5.1 System prompt assembly

**Claude Code** (`src/constants/prompts.ts:444-577`) builds a sectioned prompt with an explicit **cache boundary marker**: everything before `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` is static and cacheable cross-org (`scope:'global'`); everything after (session guidance, memory, env info, MCP instructions, scratchpad) is dynamic. Comments in the file document a real bug class — a conditional placed on the wrong side of the boundary multiplies the cache-prefix hash variants 2^N and silently destroys cache hit rates (`prompts.ts:343-351`). Three things stand out as *techniques*:

1. **Prompt text is an experimental subject.** Sections are gated by A/B flags with measured effects recorded in comments: numeric length anchors ("≤25 words between tool calls… research shows ~1.2% output token reduction vs qualitative 'be concise'", `prompts.ts:529-537`); a verification-agent contract behind `tengu_hive_evidence` (`prompts.ts:390-395`).
2. **Prompt text is a per-model counterweight.** `@[MODEL LAUNCH]` annotations tie paragraphs to specific model quirks: "False-claims mitigation for Capybara v8 (29-30% FC rate vs v4's 16.7%)" gates a faithful-reporting paragraph (`prompts.ts:237-242`); an over-commenting counterweight gates comment-discipline rules (`prompts.ts:204-213`).
3. **Behavioral policy lives here, not in code.** "Executing actions with care" (reversibility, blast radius, confirm-before-risky), tool-preference rules, tone rules — the harness *tells* the model and trusts it.

**ci2lab** (`harness/prompts.py:30-117`) joins a static `system.md` (119 lines: operating principles, tool table, argument names, safety, finishing), a read-only-session notice when write tools are hidden, environment block, project memory (`CI2LAB.md`/`AGENTS.md` merged, 12K cap), skills catalog, Yard catalog, MCP status, and fenced-tool instructions only when the model lacks native calling. The principles encode the same policies Claude Code's prompt does (ground answers in tool results, verify before reporting, plan with todos) — but compressed to fit small windows, with enforcement delegated to runtime gates instead of trust.

### 5.2 Mid-conversation steering

This is where the two philosophies are most visible:

- **Claude Code steers with `<system-reminder>` attachments**: todo-staleness reminders after 10 assistant turns without a `TodoWrite` (throttled to every 10, `attachments.ts:254-256,3266-3317`), plan-mode re-injection every Nth turn, skill-discovery suggestions, changed-file notices, queued user messages folded into the current turn (`query.ts:1547-1643`). Hooks (27 events, four types including LLM-judge "prompt" hooks and agentic "agent" hooks, `schemas/hooks.ts`) let *users* inject steering; the harness itself injects remarkably little correction.

- **ci2lab steers with 11 bounded nudges** (inventory in `loop.py`): loop-break, unparsed-tool-syntax teaching, stop-tools ("answer now"), web-capability ("you *do* have web_search"), todo-incomplete (max 3/turn — the "stops after step 1" fix), described-but-not-written, ungrounded-answer, web-fetch-failure redirect, policy explanation, edit follow-ups, and a final-round wrap-up that disables tools and forces a handoff. Plus two mechanical memory aids re-injected every round: the **request anchor** (user prompt + todo snippet, previous copy stripped so only one exists, `loop.py:552-601`) and the **progress digest** (wrote/ran/inspected/last-failure, built from the evidence ledger, `context/progress.py:68`) — a working memory that survives aggressive compaction.

Every ci2lab nudge is *bounded* (fires once, twice, or three times, then gives up or aborts) — the same discipline Claude Code applies to its recovery paths (3 autocompact failures, 3 output-token recoveries). Both teams independently learned that unbounded automatic correction creates loops worse than the ones it fixes.

### 5.3 Grounding: the technique ci2lab has and Claude Code doesn't

ci2lab maintains an **evidence ledger** of every tool call in the turn (`grounding_review/evidence.py:45`) and runs a deterministic, zero-token review of the final answer (`rules.py:95`): action claims require mutation evidence, "tests pass" requires runtime evidence, cited files require read evidence, URLs must have been fetched, and identifier-shaped codes (`ERR-4219`, `JIRA-1042`) that appear in neither prompt nor tool output are flagged as invented (`_CODE_TOKEN_RE`, `rules.py:68-72`). On failure: bounded re-prompt (2×), then the harness **replaces the answer with a guarded uncertain one** (`review.py:45`) — it structurally refuses to relay unverified claims. The ungrounded-answer gate similarly blocks a zero-evidence final answer to a workspace-referencing prompt (`loop.py:1232-1255`), and a completion verifier can spawn an independent validator subagent (3×/turn max, lenient on low confidence, `verifier.py:46,141-149`).

Claude Code addresses the same failure mode (false completion claims) almost entirely in prompt text — the Capybara-v8 mitigation paragraph above — plus an *experimental, A/B-gated, ant-only* verification-agent contract that spawns an adversarial verifier subagent for non-trivial work (`prompts.ts:390-395`). Its own comments quantify why this matters: a 29-30% false-claims rate on an internal model generation. There is no deterministic middle layer between "trust the prompt" and "spend a whole subagent run."

---

## 6. Context management

Same layered architecture, opposite driving constraint.

| Layer | Claude Code | ci2lab |
|---|---|---|
| Lossless first | History snip; superseded-read handling via `readFileState` | `prune_superseded_reads` — stub all but freshest read of each path, always on (`compact.py:173`) |
| Cheap clearing | Microcompact: clear old tool results, keep N recent; **time-based** (cache already cold) and **cache-editing** variants — the latter deletes blocks via the API's cache-edit so the cached prefix survives (`microCompact.ts:36-50,249-305`) | Micro-compact at 65% of window: stub tool results >200 chars beyond last 3; inverted allow-list so new tools are covered by default (`compact.py:19-33,90`) |
| Summarization | Autocompact at `window − 13K` tokens: 9-section structured summary prompt (intent, files+code, errors, all user messages, pending, next step), 20K output reserve, 3-failure circuit breaker (`autoCompact.ts:30,62-91`; `compact/prompt.ts:61-267`) | LLM summary at 80%: transcript rendered with 500-char tool results, one chat call against `prompts/compact.md`, keep last 6 messages, 3-failure fallback to mechanical trim (`compact.py:210-302`) |
| Hard floor | Blocking limit at `window − 3K`; staged overflow recovery: context-collapse drain → one-shot reactive compact, errors withheld from SDK consumers mid-recovery (`query.ts:1085-1183`) | `trim_messages` before every call: drop oldest middle messages to budget, never the last (`trim.py:22`) |
| Accounting | Canonical: last response's actual `usage` + estimate of messages since, walking back over split parallel-call records (`tokens.ts:226-261`) | `len/4` heuristic × 4/3 conservative factor (`compact.py:51-53`) |

**Claude Code's distinctive investment is cache economics.** Exactly one message-level cache breakpoint per request, tuned to the server's KV-page eviction (`claude.ts:3063-3211`); per-section `cache_control` derived from the boundary marker; a whole cache-break *detection* subsystem hashing system+tools+model+betas to catch accidental busts (`promptCacheBreakDetection.ts`); 1-hour TTL latched per session; tool lists sorted for stability. At Anthropic's scale, a 20K-token cache bust per turn is a product-economics bug, and the source treats it with the seriousness of a correctness bug (PR references in comments: #24490, #24171).

**ci2lab's distinctive investment is fitting in small windows**: firing compaction at 65%/80% of an 8K–32K window, the progress digest so compaction can't erase the thread, `num_ctx` actually honored by using Ollama's native endpoint (the `/v1` shim silently ignores it — `backends/ollama.py:1-10`), hardware-capped window selection, and for the review pipeline a chunk-packing planner with a lost-in-the-middle discount (`USABLE_FRACTION = 0.6`) that **aborts with a model recommendation rather than ship an incomplete review** (`context_budget.py:35-65,160`).

One place these collide: ci2lab's anchor mechanism *rewrites history every round* (strip previous anchor, append new one). On local inference this invalidates the KV-cache prefix from the strip point forward, forcing re-evaluation of most of the prompt each round — the exact failure mode Claude Code's append-only discipline and cache-edit deletions are engineered to avoid. On small windows the cost is modest; on 32K+ contexts with a 32B model it is likely the dominant per-round latency term. (Improvement §7.1.)

---

## 7. Multi-agent

**Claude Code: general-purpose parallelism, model-driven.** The `Task`/`Agent` tool recursively invokes the same `query()` loop in-process (`runAgent.ts:748-757`). It declares itself read-only and concurrency-safe (`AgentTool.tsx:1264-1275`), so a single assistant message can fan out up to 10 parallel subagents. Agent definitions are markdown frontmatter (`.claude/agents/*.md`: tools, model, effort, permissionMode, mcpServers, hooks, skills, isolation) with source precedence built-in < plugin < user < project < flag < policy. Restriction is subtractive: per-agent tool allow/deny lists, blocked recursion, async agents auto-denied permission prompts, read-only agents stripped of CLAUDE.md/gitStatus to save tokens (`runAgent.ts:386-498`). Background tasks auto-detach after 120s; results return as the tool result; teams/coordinator/workflow modes exist behind flags. The *orchestration logic itself* lives in the model's head — the harness provides spawn, restrict, and return.

**ci2lab: fixed pipeline, harness-driven.** `run_multi_agent` (`orchestrator.py:3230`) first runs a **deterministic intent classifier** (no LLM, no I/O — `intent.py`) that decides the phase list and risk posture; then executes planner → researcher → coder → validator → reviewer → security-reviewer with a bounded repair loop (validator fails → coder retries, max 2), preferring **deterministic validation contracts** over judge subagents where possible, and role specs with forbidden-tool lists *plus* violation detection even when the allow-list already blocks (`roles.py:98`, `runner.py:22-43`). The peer-review flow adds the strongest idea in the codebase: LLM lenses propose findings, then a deterministic grounding gate verifies each one — a `manuscript` claim must contain a verbatim quote that actually occurs, an `absence` claim is refuted if the term exists, an `external` claim requires the URL to have been fetched this run — and quarantines what fails (`grounding.py:228-371`).

The contrast is trust again: Claude Code lets agents coordinate agents (its verification contract even makes the *parent* responsible for adversarial review); ci2lab assumes any individual agent may hallucinate and interposes machine checks at every phase boundary. Claude Code's approach scales to arbitrary task shapes; ci2lab's produces *auditable* runs (schema-versioned trace records, per-phase artifacts under `runs/<id>/phases/`) at the cost of flexibility.

---

## 8. Permissions and security

**Claude Code** runs a layered decision pipeline (`permissions.ts:1158-1319`) with a strict order: blanket deny → blanket ask → tool-specific check → **bypass-immune safety check** (protects `.git/`, `.claude/`, shell configs even in `bypassPermissions` mode) → mode resolution → allow rules → default-ask. Its most distinctive element is **auto mode**: an LLM security classifier adjudicates otherwise-ask actions, fails *closed* when unavailable (gated, 30-min refresh), tracks denial streaks, and falls back to human prompting past limits (`permissions.ts:518-927`). Enforcement is defense-in-depth: rule matching per Bash subcommand, injection detection, and an actual OS sandbox (Seatbelt/bubblewrap) — with the sandbox's `excludedCommands` explicitly documented as convenience, not a boundary. 27 hook events give users programmable policy (a PreToolUse hook can allow/deny/rewrite input — but deny rules and the safety check still override a hook's allow).

**ci2lab** makes the permission system itself *swappable* (`security/engine.py:62-78`): `ci2lab` (hard guards only), `opencode_experimental` (permission layer only), and the default `claude_experimental` (hard guards **then** a Claude-style allow/ask/deny layer — an explicit reimplementation of Claude Code's model). Hard guards are un-bypassable even with `--yes`: security profiles, path confinement + secret-file blocking (`.env`, keys), and the bash blocklist. Distinctive elements: session-approval fingerprints scoped to an orchestration run (an "allow for session" survives phase boundaries but not runs), mandatory diff-preview confirmation for writes, a JSONL audit trail on *every* gate decision, and — unique among the two — a ~3,500-line **audit apparatus that compares the engines against each other** (`claude_deterministic_matrix.py`, `claude_live_audit.py`, `comparison.py`), treating the permission layer as a research subject.

Honest gaps on both sides: ci2lab has **no OS-level sandbox** — its guards are path/regex analysis of commands, which motivated attackers (or creative models) can evade in ways bubblewrap cannot; Claude Code's `bypassPermissions` mode, killswitches notwithstanding, still ultimately relies on the sandbox being enabled to make "YOLO mode" survivable. Both treat prompt injection mostly at the prompt level ("flag it to the user").

---

## 9. Effectiveness

What can honestly be concluded from source plus repo evidence — neither codebase ships public benchmark numbers.

**Claude Code's effectiveness case is industrial.** The source *is* the evidence: it encodes measured behavior at every layer — A/B experiment comments with effect sizes ("~1.2% output token reduction"), model-generation regression data ("29-30% FC rate vs 16.7%"), PR-referenced cache-bust bug classes, staged recovery paths that only exist because each failure mode was hit at scale, and telemetry (GrowthBook + OpenTelemetry) that closes the loop in production. Its reliability strategy — few mechanisms, all infrastructural, everything else delegated to model quality — is only viable *because* Anthropic co-trains the models on this harness's tool schema and behavior. The effectiveness risk it accepts: when the model is wrong confidently (false completions), the harness has no independent check in the shipped path; the mitigation is prose, and the real check (verification agent) is still an internal experiment.

**ci2lab's effectiveness case is instrumental and (so far) unquantified in-repo.** What exists: a benchmark harness purpose-built for *attribution* — H1 (product vs Codex CLI vs Claude Code), H2 (harness isolation: same open model under ci2lab vs Codex), H3 (single- vs multi-agent internal control), k=5 samples, unbiased pass@k, cost via token prices, exit-code/exact-match oracles with **no LLM judge**, hidden tests injected only after the agent stops (`bench/verifier.py`, `bench/runner.py:171-172`), and a `false_positive` metric that formalizes exactly the failure Claude Code fights with prose: *claimed done but functionally wrong or evidence-free* (`runner.py:239-241`). The recent hardening wave (commit `02bf780`) is traceable task→mechanism: the CLI-01 planted `ERR-7731` needle motivated the invented-code guard; the H3 evidence-trap task motivated the ungrounded-answer gate; red-test iteration motivated `command_failed` semantics. What does *not* exist: committed results (`benchmarks/results/` is git-ignored), so no win-rates can be cited here. The quality floor is real though: ~905 deterministic tests, mock-first behavioral evals, ruff+mypy-clean CI.

**Comparative assessment by property:**

| Property | Advantage | Why |
|---|---|---|
| Peak capability | Claude Code | Frontier models + co-trained harness; no cap on rounds, parallel tools, subagent fan-out |
| Robustness to weak models | ci2lab | Five-parser leniency, JSON repair, nudges, bounded budgets — Claude Code would simply fail on models that miss native tool syntax |
| Token/cost efficiency at scale | Claude Code | Cache-preservation engineering end to end |
| Latency | Claude Code | Streaming + mid-stream tool execution + parallel read batches vs sequential, non-streamed rounds |
| Resistance to false completions | ci2lab | Deterministic evidence gates + guarded answers vs prompt text (its own comments concede the residual rate) |
| Auditability / reproducibility | ci2lab | Deterministic oracles, run artifacts, schema-versioned traces, engine-comparison matrices |
| Security depth | Claude Code | OS sandbox + injection parsing + classifier; ci2lab's guards are analysis-only |
| Extensibility by users | Claude Code | Hooks, plugins, agent/skill markdown, MCP client+server, SDK |

---

## 10. Improvements

### 10.1 For ci2lab (adopt from Claude Code)

1. **Read-before-edit + staleness gate.** Make `edit_file` validation require a prior successful `read_file` of the path this session (the loop's `satisfied_reads` machinery already tracks reads) and reject if mtime changed since (`FileEditTool.ts:275-311` is the reference). Today only a post-hoc hint exists (`file_hints.py:21-32`); on multi-step edits with weak models this is a live corruption risk the benchmark's `bug-02` shape would eventually expose.
2. **KV-prefix-friendly history.** Stop stripping/re-inserting the request anchor mid-history each round; append steering at the tail only (or fold it into the progress digest), keeping history append-only so llama.cpp/vLLM/Ollama prefix caching survives. Measure prompt re-eval time per round before/after — this is likely the cheapest large latency win available, and it is the local-inference mirror of Claude Code's boundary-marker discipline.
3. **Parallelize read-only batches.** `capabilities.py` already classifies tools; consecutive `READ_ONLY_TOOLS` calls in one round can run in a small thread pool (the `skipped_after_error` guard already defines batch-failure semantics). Claude Code's partition-into-batches algorithm (`toolOrchestration.ts:91-116`) drops in almost directly.
4. **Deferred tool schemas.** 32 function schemas ride every round of an 8K-window session. Adopt Claude Code's defer-and-search pattern (`Tool.shouldDefer` + ToolSearch) or a static tiering: core 10 schemas always, the rest summarized in one line each with a `load_tool` call to expand. This directly buys back context for the models that need it most.
5. **Transport retry with backoff.** `llm_errors.py` classifies well but fails fast; local servers drop connections under memory pressure routinely. A bounded jittered-exponential retry (Claude Code: base 500ms, cap 32s, jitter 25%) at the backend level would convert many `llm_error` run deaths into pauses.
6. **User-configurable hooks.** ci2lab's `emit_hook_event` exists but is internal. Exposing pre/post-tool command hooks in `ci2lab.yaml` (with the Claude Code rule that a hook's allow cannot override a hard guard) would give the security work a user-programmable layer and help the paper's "scaffolding" story generalize.
7. **Todo-staleness cadence.** ci2lab nudges todos only at finalize-time; Claude Code reminds after 10 turns of silence (`attachments.ts:254-256`). A mid-flight reminder would catch drift earlier on long multi-step tasks — cheap because the todo state is already in the anchor.
8. **OS-level sandbox as an optional engine.** Even a minimal bubblewrap (Linux) / Job Object (Windows) wrapper for `bash` — off by default, on for benchmarks — would move the security story from "analysis" to "containment" and make the `sec-01` refusal task a boundary test rather than a regex test.
9. **Compaction summary prompt structure.** Claude Code's 9-section compact prompt (verbatim user messages, files+code sections, pending tasks, next step; `compact/prompt.ts:61-267`) is battle-tested against post-compaction amnesia; ci2lab's `compact.md` should adopt the enumerated-sections + verbatim-quotes pattern if it hasn't.

### 10.2 For Claude Code (adopt from ci2lab)

1. **A deterministic grounding layer.** An evidence ledger keyed on its existing tool capabilities, an ungrounded-final-answer check, and the invented-identifier guard would cost zero tokens and no latency, and directly attack the false-claims rate its own comments quantify — as a floor *under* prompt mitigations and far cheaper than the verification-agent contract (which could then be reserved for the cases the deterministic layer flags). ci2lab demonstrates the shape: capability-derived evidence classes + claim-pattern rules + bounded re-prompt (`grounding_review/`).
2. **Trajectory repetition detection.** Autonomous modes (proactive/tick-driven, background agents, token-budget continuation) can loop on the same failing action with no harness backstop — only budget exhaustion stops them. A tool-call signature deque with a bounded nudge-then-stop (ci2lab: `loop.py:1350-1381`) is cheap insurance precisely where no human is watching.
3. **Registry/prompt drift tests.** The leak itself shows documentation drifting from source. ci2lab's cross-registry consistency test pattern (name set ↔ schema ↔ dispatch ↔ capability, enforced in CI) applied to tool names/aliases/prompt references would catch a class of silent drift that cache-break detection doesn't.
4. **Same-batch dependency guard.** When a serial batch's earlier tool fails, later *mutating* calls from the same assistant message still execute. ci2lab skips them with an explanatory result (`loop.py:1411-1420`), preventing "committed the placeholder because the generate step failed" incidents; the model can always re-issue.
5. **False-positive completion as a first-class eval metric.** ci2lab's `false_positive = looks_successful ∧ (¬functional ∨ ¬evidence)` (`bench/runner.py:239-241`) is a better target than false-claims prose mitigation alone — it makes the failure measurable per release and per model.
6. **Deterministic pre-verification in review flows.** Before spending adversarial verifier subagents on a finding, verify mechanically what can be: cited file/line exists, quoted snippet occurs verbatim, claimed symbol resolves. ci2lab's quote/absence/fetched-URL gate (`grounding.py:371`) shows the pattern; it would cut verification cost and kill hallucinated findings before they reach a judge.

### 10.3 Shared gaps

- **Semantic loop detection.** Both detect only exact repetition (ci2lab) or nothing (Claude Code); neither notices *semantically* equivalent thrashing (alternating between two failing approaches). A cheap embedding-or-edit-distance check over recent tool signatures would cover both.
- **Prompt-injection defense is declarative in both.** Tool results carrying instructions are handled by "flag it" prose. Content-provenance tagging (marking tool-result spans as untrusted at the message level) is an open improvement neither implements.
- **Steering mechanisms are themselves unmeasured.** Claude Code A/Bs prompt *text* but not (visibly) reminder cadences or recovery limits; ci2lab has the bench to measure its nudges but no committed ablation results yet — the planned ablation-flag work is exactly right, and Claude Code would benefit from the same discipline.

---

## 11. Bottom line

These are two answers to the same engineering question — *how do you make an LLM reliably operate tools in a loop?* — optimized for opposite ends of the model-capability spectrum.

Claude Code is a mature product harness whose sophistication concentrates where its constraints are: prompt-cache economics, API failure recovery, permission safety at scale, and behavioral steering through relentlessly A/B-tested prompt text. It can afford to trust the model with the trajectory because the model was trained to be trustworthy in this exact harness — and its one visible soft spot (unverified completion claims, mitigated by prose and an experimental verifier) is the direct price of that trust.

ci2lab is a research harness whose sophistication concentrates where *its* constraints are: extracting reliable agentic behavior from small local models through tolerant parsing, bounded mechanical steering, deterministic grounding gates, and an attribution-grade benchmark. Its soft spots are the mirror image: sequential and non-streamed execution, no OS sandbox, cache-hostile history rewriting, and — as of `02bf780` — no committed numbers yet proving the gates earn their keep.

Each harness's strongest idea is the other's clearest gap: Claude Code's cache-and-recovery engineering would make ci2lab faster and more resilient tomorrow; ci2lab's deterministic evidence layer is the cheap, model-independent integrity floor Claude Code hasn't shipped. The convergences — layered compaction with keep-recent-N, bounded self-correction, offload-over-truncate, markdown-frontmatter extensibility, read-only capability classification — are convergent evolution under shared physics, and a decent map of what any serious agent harness ends up needing.
