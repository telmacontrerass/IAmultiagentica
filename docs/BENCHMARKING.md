# IAmultiagentica Benchmarking Plan

Internal methodology for benchmarking the `ci2lab` multi-agent architecture
against **OpenAI Codex CLI** and **Claude Code**, for a formal research paper.

> Status: **methodology agreed (2026-06-29); no suite code written yet.** Core
> decisions are locked (see §7): run H1 + H2 + H3; ci2lab single-agent and
> multi-agent are **separate conditions**; **k = 5** samples; cost is measured as
> **tokens, then converted to USD** at published per-token prices; the benchmark
> suite lives **apart from the test suite** (`benchmarks/` for tasks/results,
> `ci2lab/bench/` for code). **Hard constraint: the whole benchmark runs at zero
> marginal API cost** — competitors run under existing Codex/Claude Code
> subscriptions, and `ci2lab` plus the shared H2 model run on local models. This
> document defines the task taxonomy, metrics, harness architecture, and the
> implementation checklist that follow from those decisions.

---

## 0. Research question and scope

We are not benchmarking "which LLM is smartest." We are benchmarking **agentic
systems end-to-end**: prompt in → tool-using loop → verifiable outcome. The
paper's central claim should be framed as one of:

- **H1 (system-vs-system, honest default):** As shipped, how does the
  local-first `ci2lab` stack (open model on Ollama + ReAct/multi-agent harness)
  compare to Codex CLI and Claude Code (frontier hosted models + their
  harnesses) on a fixed task suite, across correctness, token/cost, and latency?
- **H2 (harness isolation — the strong result, at zero cost):** Hold the *model*
  fixed and vary only the harness. The constraint (§2.1): a subscription only
  powers its **own** vendor's harness, so we can't put a frontier model under
  ci2lab for free, nor cleanly put an open model under Claude Code. The free,
  non-fragile same-model evidence that *is* available:
  - **ci2lab vs Codex on one self-hosted open model M.** Codex runs M natively
    (`codex --oss`, or a custom OpenAI-compatible provider base-URL'd to a local
    server); ci2lab points its pluggable backend (`backend`, `backend_url`,
    `model`; see [`docs/STRUCTURE.md`](STRUCTURE.md) and `harness/backends/`) at
    the same M (M = `qwen2.5-coder:32b`, see §5.7). **Same model, two harnesses,
    local compute only.**

  Claude Code is **deliberately excluded** from H2: pointing it at an open model
  needs a fragile Anthropic-API proxy, abandons the subscription, and tests its
  scaffolding-on-a-weak-model rather than the product. We state that as a
  limitation rather than chase it.
- **H3 (internal control — cleanest, also free):** `ci2lab` single-agent vs
  `ci2lab-multi` on the same model M — no competitor, no proxy, no confound;
  isolates *our* orchestration value outright.

H1 is the product story; **H2 + H3 are the harness-isolation evidence.** None
needs a paid API.

> **On cost:** competitors run under your existing **Codex/Claude Code
> subscriptions** (Sign in with ChatGPT / Claude account — no API key); ci2lab
> and M run **locally**. The **entire benchmark has zero marginal API cost.**
> Claude Code appears only in H1 (under subscription); the only real constraint
> is subscription rate limits — see §2.5.

---

## 1. What already exists (build on this, don't rebuild)

The repo already ships a working eval framework under `ci2lab/evals/`. The new
work is an *extension*, not a greenfield harness.

| Capability | Where | Reuse for benchmarking |
| --- | --- | --- |
| Declarative task spec (JSON) | `ci2lab/evals/task.py` → `EvalTask.from_dict` | Add `verifier`, `category`, `k_samples`, `hidden_setup` fields |
| Isolated per-task workspace + fixtures | `task.setup_workspace`, `runner.run_eval_suite` (`results_dir/workspaces/<id>`) | Already gives us env isolation; add git-based reset for repo tasks |
| In-process ci2lab run | `harness.run_agent(prompt, selection, config=config) -> str` | The ci2lab adapter wraps this directly |
| Multi-agent run | `harness.multiagent.run_multi_agent(prompt, selection, config=config) -> str` | Second ci2lab variant under test |
| Token accounting | `AgentConfig.token_usage` (`TokenUsageState`) populated after the run; persisted to `runs/<id>/token_usage.jsonl` | Read `config.token_usage.session` for prompt/completion/total — **no new instrumentation needed** |
| Tool-call log w/ timing | `runs/<id>/tool_calls.jsonl` (`tool`, `ok`, `outcome`, `duration_ms`, `error`) | Source for tool-count, tool-error rate, per-tool latency |
| Run status | `run.json` (`success \| llm_error \| max_rounds \| interrupted`) | Distinguishes "wrong answer" from "ran out of rounds/crashed" |
| Grading (heuristic) | `task.evaluate_task` → `TaskEvalResult` | Keep for behavioural checks; **add an exit-code oracle alongside it** |
| Runner + results | `runner.run_eval_suite` → `results.jsonl` + `summary.json` | Generalize the runner over an *agent adapter*, not just `run_agent` |
| Mock vs live | `--live` flag; `mock_responses` per task | Benchmarks always run **live**; mock stays for CI determinism |
| CLI surface | `ci2lab evals run [--live] [--model TAG] [--task ID] [--tasks-dir PATH]` | Pattern to mirror in a **new, separate** `ci2lab bench run` verb with an `--agent {ci2lab,ci2lab-multi,claude-code,codex}` dimension (§5.6) |

**Gaps to close for the paper:**

1. **Functional-correctness oracle** — current checks are heuristic (tool used?
   substring in answer?). The paper needs **Pass@1 on hidden tests**: a verifier
   command run in the workspace after the agent finishes, graded by exit code.
2. **Cross-agent adapters** — the runner is hardwired to `run_agent`. We need a
   uniform `AgentAdapter` so Codex CLI and Claude Code run through the same
   pipeline.
3. **Metrics capture in results** — `TaskEvalResult`/`EvalRunSummary` don't yet
   carry tokens, cost, or wall-clock. Thread them through.
4. **Repo-based bug tasks** — fixtures today are flat files; bug-fix tasks need a
   seeded git repo with FAIL_TO_PASS / PASS_TO_PASS test sets.
5. **Sampling + statistics** — k samples per task, Pass@k, and confidence
   intervals.

---

## 2. Methodological framing and threats to validity

Put this **up front in the paper**, not buried. Reviewers will attack exactly
these points.

### 2.1 The model-asymmetry confound (the big one)

`ci2lab` runs **local open models** (e.g. `qwen2.5-coder:7b` on Ollama);
Claude Code and Codex CLI run **frontier hosted models**. A raw H1 chart that
shows `ci2lab` losing on correctness mostly measures *model capability*, not
*harness quality*. Mitigations, in order of rigour:

- **Always report the model + backend each system used.** No anonymous bars.
- **Run the H2 controlled comparison:** ci2lab vs **Codex** on one
  **self-hosted open model** M (Codex runs M via `--oss`/custom provider; ci2lab
  via config-only backend swap — see §0). The model is held constant, so the
  delta is attributable to orchestration. This is the headline experiment and
  costs only local compute. Claude Code can't join this for free (its
  subscription only drives its own harness; an open-model proxy is fragile), so
  the cross-harness same-model point comes from Codex, and **H3** (ci2lab single
  vs multi on M) backs it up confound-free.
- **Report a capability-normalized view:** correctness *given* the model, plus
  tokens/latency *per solved task* (efficiency is comparable even when raw
  capability isn't).

### 2.2 Non-determinism

Local and hosted models are stochastic. Controls:

- Fix `temperature` (0 for correctness runs; document it), fix seeds where the
  backend supports it, pin model **versions/digests** (Ollama digest, hosted
  model snapshot id), pin each agent CLI **version**.
- Run **k ≥ 5 samples** per (task, agent). Report Pass@1 as the mean over
  samples and the unbiased Pass@k estimator; attach bootstrap CIs.

### 2.3 Oracle integrity (no overfitting / no leakage)

- **Hidden tests are injected at grading time**, after the agent stops, into a
  path the agent never saw. The agent cannot read, edit, or satisfy-by-coincidence
  the grader.
- Bug tasks use **PASS_TO_PASS** regression tests so "delete the failing
  assertion" or "patch the test" does not score as a fix.
- Forbid edits to the test directory in the verifier (fail if the agent touched
  it).

### 2.4 Other threats to name explicitly

- **Harness-overhead vs model-capability confound** → addressed by H2.
- **Network variance** inflates hosted-tool latency; local has cold-start
  (model load into VRAM). Report **cold vs warm** separately and warm up before
  timing.
- **Small-N power** → keep the suite reproducible and report CIs; don't
  over-claim on 7 tasks.
- **Prompt sensitivity** → every agent gets the **byte-identical** task prompt;
  no per-agent prompt tuning. Document this as a deliberate fairness constraint
  (it slightly disadvantages tools that expect their own prompt conventions —
  acknowledge it).
- **Evaluator bias** → grading is exit-code based, not LLM-judged, wherever
  possible. If any task needs an LLM judge, use a fixed rubric + a model none of
  the three systems share, and report judge agreement.

### 2.5 How the benchmark runs at zero API cost (auth model)

Two notions of "cost" stay separate:

- **Cost we *measure*** — tokens/USD consumed *by each system under test* per
  task. A primary metric (§4.2), derived from tokens.
- **Cost we *spend*** to run the benchmark — our own bill. Target: **$0
  marginal.**

How each condition is run, and what it costs us:

| Condition | How it's run | Our marginal cost |
| --- | --- | --- |
| `ci2lab` / `ci2lab-multi` (H1, H2, H3) | local Ollama model(s) | $0 (local compute) |
| **Codex CLI** — H1 | **ChatGPT subscription** (Sign in with ChatGPT) | $0 marginal (flat sub) |
| **Codex CLI** — H2 | `codex --oss` / custom provider → shared open model M | $0 (local compute) |
| **Claude Code** — H1 only | **Claude Pro/Max subscription** (`/login`) | $0 marginal (flat sub) |

The competitor CLIs run headlessly under their subscriptions with **no API key**
— and they still emit the telemetry we need: `claude -p --output-format json`
returns `usage` (input/output/cache tokens) and `total_cost_usd` (a *computed
equivalent*, not a charge), and `codex exec --json` emits token-usage events. So
metrics survive on subscription auth.

**The real constraints (not dollars):**

- **Subscription rate limits.** Pro/Max and ChatGPT plans cap usage over rolling
  windows; 7 tasks × k=5 × conditions can bump them. Pace the runs (sequential
  already; add backoff/sleep between samples) and spread the matrix over time.
  *Verify headless subscription auth + telemetry on day one (§6 spike).*
- **Codex on the open model M (H2).** Low risk — Codex's `--oss`/custom-provider
  path is officially supported. Smoke-test that `codex exec --json` against M
  completes and emits token usage before the full H2 run.
- **Claude Code is H1-only (decided §7).** We do **not** route it to an open
  model: the proxy is fragile and abandons the subscription. The cross-harness
  same-model evidence comes from Codex-on-M + H3 (§0).
  Running the CLIs headlessly under subscription is within normal use; note in
  the paper that Codex-on-M exercises the open model, not the subscription.

Because nothing is billed per token, **every USD figure in the results is
imputed from tokens** via the price table (§4.2) — there is no real invoice to
reconcile against.

---

## 3. Task taxonomy

Seven core tasks across three families, each targeting a distinct failure mode.
All are small, reproducible, and gradable by an exit-code or exact-match oracle.
An eighth (safety) is optional and leverages the harness's existing security
grading.

Design rules for every task:

- **Self-contained fixture** created fresh per run (no network, no external
  deps beyond a pinned `pytest`/`bash`).
- **Hidden oracle** the agent never sees during the run.
- **Single, unambiguous pass criterion.**
- **Bounded** (`max_rounds`, wall-clock cap) so a stuck agent fails closed.

| ID | Family | Failure mode tested | Pass criterion (oracle) |
| --- | --- | --- | --- |
| `CLI-01` | CLI exec | Large-file tool selection (grep vs read-all → context blowup) | Exact planted token in final answer |
| `CLI-02` | CLI exec | Run a script, parse stderr, diagnose failing step | Final answer names the failing command + exit code |
| `QA-01`  | Code Q&A | Locate a symbol in an unseen multi-file project (navigate vs hallucinate) | Answer contains correct `file:function` + return type; **no edits** |
| `QA-02`  | Code Q&A | Multi-hop trace: CLI flag → config → consumption site | Answer lists the 3 hops in order |
| `BUG-01` | Bug fix | Localize + patch root cause of one failing unit test | FAIL_TO_PASS passes **and** PASS_TO_PASS still pass |
| `BUG-02` | Bug fix | Multi-file regression (off-by-one in parser + caller) | FAIL_TO_PASS passes, PASS_TO_PASS pass, no test-dir edits |
| `FEAT-01`| Code gen | Implement a stubbed function to a hidden spec | Hidden spec tests pass |
| `SEC-01` *(opt.)* | Safety | Refuse/blocked dangerous command under policy | Dangerous tool blocked by security engine (existing grading) |

### Task definitions (review these in detail)

Each definition lists what the agent sees, what is hidden, and how it's graded.
Field names map onto `EvalTask` plus the proposed new fields (`verifier`,
`hidden_setup`, `category`, `k_samples`).

---

#### `CLI-01` — Find the needle in a large log

- **Prompt (verbatim, all agents):** "The file `app.log` in this directory
  contains exactly one line with a fatal error code of the form `ERR-XXXX`.
  Report that error code and the line number it appears on."
- **Workspace:** `app.log`, ~50k lines of plausible-looking log noise with a
  single planted `ERR-7731` at a known line.
- **Hidden from agent:** the expected code/line (oracle only).
- **Failure mode:** an agent that `read_file`s the whole log blows its context
  and may truncate/miss it; the competent move is `grep`. We measure both
  correctness and token cost — this task is where the token-efficiency story is
  sharpest.
- **Oracle:** final answer contains `ERR-7731` **and** the correct line number
  (exact match). No workspace mutation expected.
- **Schema:** `expected_final_answer_contains: ["ERR-7731", "<line>"]`,
  `forbidden_tools: ["write_file","edit_file"]`, `max_rounds: 8`.

#### `CLI-02` — Run the build script, diagnose the failure

- **Prompt:** "Run `./build.sh` and tell me which command failed and its exit
  code. Do not modify any files."
- **Workspace:** `build.sh` that runs three steps; step 2 fails deterministically
  (e.g. references a missing file) with a distinct exit code.
- **Hidden:** the identity of the failing step + exit code (oracle).
- **Failure mode:** the agent must actually execute (`bash`), read stderr, and
  attribute the failure — not guess from the script source alone.
- **Oracle:** final answer names the failing command and the exit code; the
  `bash` tool was invoked (`expected_tool_groups: [["bash"]]`); no file edits.
- **Schema:** `expected_final_answer_contains: ["<cmd>", "<exit_code>"]`,
  `forbidden_tools: ["write_file","edit_file"]`, `max_rounds: 10`.

#### `QA-01` — Locate a symbol in an unseen codebase

- **Prompt:** "In this project, which function computes the shipping discount,
  in which file is it defined, and what type does it return?"
- **Workspace:** a small (~6-file, ~300-line) Python package with one
  `compute_discount(...) -> Decimal` buried two directories deep, plus
  distractor functions with similar names.
- **Hidden:** the answer triple (oracle).
- **Failure mode:** navigation (`glob`/`grep`/`read_file`) vs hallucinating a
  plausible-but-wrong function; resisting the distractors.
- **Oracle:** answer contains the function name, the correct file path, and
  `Decimal`; **read-only** (`forbidden_tools` includes all write tools).
- **Schema:** `expected_final_answer_contains: ["compute_discount", "<path>", "Decimal"]`.

#### `QA-02` — Trace a value across files

- **Prompt:** "Trace how the `--threshold` CLI flag reaches the code that uses
  it. List, in order, the three places it passes through."
- **Workspace:** a small CLI app where `--threshold` is parsed in `cli.py`,
  stored on a config object in `config.py`, and read in `engine.py`.
- **Hidden:** the ordered 3-hop chain (oracle).
- **Failure mode:** multi-hop cross-file reasoning; partial credit is *not*
  given — all three hops, in order.
- **Oracle:** answer contains the three file/symbol hops in the correct order
  (ordered substring check). Read-only.

#### `BUG-01` — Patch a failing unit test (single file)

- **Prompt:** "`pytest` fails in this repo. Find the root cause and fix it so the
  tests pass. Do not edit files under `tests/`." (The failing test's output is
  included in the prompt.)
- **Workspace:** a git-initialized mini-library with a planted bug in one source
  file (e.g. a boundary condition in `discount.py`).
- **Hidden setup (injected at grading time):** the FAIL_TO_PASS test
  (`tests/test_hidden.py`) **and** a set of PASS_TO_PASS regression tests.
  Optionally, a *visible* subset is present during the run so the agent has a
  reproduction; the grading set is injected fresh.
- **Failure mode:** localizing the real root cause vs patching symptoms or the
  test; not introducing regressions.
- **Oracle:** `pytest -q` exit 0 on FAIL_TO_PASS **and** PASS_TO_PASS; verifier
  fails the task if anything under `tests/` changed (git diff check).
- **Schema:** `verifier: {command: "pytest -q", expect_exit: 0,
  fail_to_pass: [...], pass_to_pass: [...], forbid_paths: ["tests/"]}`.

#### `BUG-02` — Multi-file regression bug

- Same shape as `BUG-01` but the root cause spans **two files** (an off-by-one in
  a tokenizer plus the caller that compensates for it). A minimal one-line patch
  in either file alone leaves a PASS_TO_PASS test red. Tests whether the agent
  reasons about the interaction rather than silencing the first failure.

#### `FEAT-01` — Implement to a hidden spec

- **Prompt:** "Implement the function `parse_duration(s)` in `durations.py` per
  its docstring so that the project's tests pass."
- **Workspace:** `durations.py` with a documented stub raising
  `NotImplementedError`.
- **Hidden:** the spec test suite (injected at grading), covering normal +
  edge cases (`"90m"`, `"1h30m"`, invalid input → `ValueError`).
- **Failure mode:** code generation under a test contract, including edge cases
  an eager agent skips.
- **Oracle:** hidden spec tests exit 0.

#### `SEC-01` *(optional)* — Dangerous-command refusal

- Leverages the existing `dangerous_tools` / security-policy grading in
  `evals/task.py`. A differentiator for a *local-first* agent paper: does the
  harness's security engine block a destructive `bash` command. Cheap to add
  because the grading already exists; include if we want a safety axis.

> **Difficulty ladder.** `CLI-01/QA-01` are warm-ups (most agents should pass),
> `QA-02/BUG-01/FEAT-01` are the discriminating middle, `BUG-02` is the stretch.
> A good suite has a spread so the results aren't all-pass or all-fail.

---

## 4. Evaluation metrics

Three primary axes (the user's ask) plus secondary diagnostics. Every metric is
recorded **per (task, agent, sample)** and aggregated with CIs.

### 4.1 Functional correctness — Pass@1 (primary)

- **Per-sample:** `solved ∈ {0,1}` from the **oracle exit code** (or exact-match
  for Q&A tasks). This replaces heuristic grading as the headline number.
- **Pass@1:** mean of `solved` over the k samples of a (task, agent), then
  averaged over tasks (report per-task too).
- **Pass@k** (if k>1): use the unbiased HumanEval estimator
  `pass@k = E[1 − C(n−c, k) / C(n, k)]` where `n` = samples, `c` = #correct.
  Report Pass@1 and Pass@5 at minimum.
- **Failure attribution** from `run.json` status: separate *wrong answer* from
  *max_rounds* (didn't finish) from *crash/llm_error*. A harness that stalls is a
  different failure than one that confidently answers wrong.

### 4.2 Token efficiency and cost (primary)

- **Tokens:** input (prompt) and output (completion) separately, summed over the
  run. Sources:
  - `ci2lab`: `config.token_usage.session` after `run_agent` /
    `runs/<id>/token_usage.jsonl` (already captured).
  - **Claude Code:** `claude -p ... --output-format json` → `usage`
    (input/output, incl. cache tokens) and `total_cost_usd`.
  - **Codex CLI:** `codex exec --json ...` → token-usage events.
- **Cost ($/task) — measured from tokens, by decision.** The primary, uniform
  currency is **tokens**; USD is **derived from tokens**, not read from any one
  tool's billing, so the comparison uses one consistent price model:
  - Maintain a single, version-controlled **price table** (`benchmarks/prices.json`):
    input/output USD per million tokens for every model under test, with the
    date and source. `usd = input_tok·price_in + output_tok·price_out`.
  - Apply the **same formula to all systems**, including `ci2lab`. For `ci2lab`'s
    **local** H1 runs there is no real API bill, so the USD is explicitly an
    **imputed "what this would have cost on the equivalent hosted API"** number
    (reference price = the same open model's cheapest reputable hosted rate, or
    the matched frontier model). Always label it *imputed* and report the raw
    token counts alongside.
  - The competitor CLIs' **self-reported** USD (Claude Code's `total_cost_usd`,
    a *computed equivalent* even under subscription; Codex's reported usage) is
    captured **only as a cross-check** on our token→USD conversion — not as the
    headline number — so cache/discount effects don't make the comparison
    apples-to-oranges. (Under subscription nothing is actually billed per token,
    so all reported USD is equivalent-cost, never an invoice.)
- **Efficiency view:** **tokens per *solved* task** (and the derived USD/solved)
  — this is the metric where a lean local harness can win even when raw Pass@1
  trails.

### 4.3 Wall-clock latency (primary)

- **End-to-end seconds** from prompt submission to final answer, measured by the
  harness around the adapter call (subprocess wall time for all three → fair).
- Report **median and p90** over samples; report **warm** runs as primary and
  **cold-start** (first invocation: model load / process spawn) separately.
- Note the asymmetry honestly: `ci2lab` cold-start includes Ollama VRAM load;
  hosted tools' latency includes network RTT. Warm up before timing.

### 4.4 Secondary diagnostics (cheap, illuminating)

From the existing logs, per run: **rounds used**, **tool-call count**,
**tool-error rate** (`ok=false` / total from `tool_calls.jsonl`), **% of runs
hitting `max_rounds`**, and per-tool latency (`duration_ms`). These explain
*why* one system is slower or pricier (e.g. thrashing vs efficient tool use).

### 4.5 Reporting artifacts

- `results.jsonl` — one row per (task, agent, sample) with all metrics.
- `summary.json` — aggregates per (task, agent) with means + bootstrap 95% CIs.
- A results table (Pass@1, tokens, $/task, latency) + plots
  (Pass@1 bar, tokens-vs-correctness scatter, latency box). Paper-ready.

---

## 5. Harness architecture

A thin orchestration layer over the existing `evals/` runner. Five components.

```
                        ┌────────────────────────────────────────┐
                        │  Benchmark runner (extends run_eval_suite)│
                        │  for task × agent × sample:               │
                        │    1. provision fresh workspace (git reset)│
                        │    2. adapter.run(task, workspace)         │
                        │    3. inject hidden tests                  │
                        │    4. verifier(workspace) -> solved        │
                        │    5. collect metrics -> results.jsonl     │
                        └───────────────┬────────────────────────────┘
                                        │  AgentAdapter (uniform interface)
              ┌─────────────────────────┼──────────────────────────┐
              ▼                          ▼                          ▼
      ci2lab adapter            claude-code adapter         codex adapter
   (in-process run_agent /     (subprocess: claude -p      (subprocess: codex
    run_multi_agent; reads      --output-format json)       exec --json)
    config.token_usage)        parses usage + cost          parses token events
```

### 5.1 `AgentAdapter` (the key abstraction)

A protocol with a single method, returning a normalized result. This is the
seam that makes the comparison fair: the runner, tasks, workspace provisioning,
and grading are identical across systems; only the adapter differs.

```text
AgentAdapter.run(task, workspace, *, model, max_rounds, timeout) -> RunResult

RunResult:
  final_answer:   str
  solved:         bool            # filled by the verifier, not the adapter
  prompt_tokens:  int | None
  completion_tokens: int | None
  cost_usd:       float | None    # None for local/no-API
  wall_clock_s:   float
  rounds:         int | None
  tool_calls:     int | None
  tool_error_rate: float | None
  status:         str             # success | max_rounds | error | timeout
  transcript_path: str            # raw stdout/json for audit + the paper appendix
```

**Three adapters:**

- **`ci2lab` / `ci2lab-multi`:** call `run_agent` / `run_multi_agent` in-process
  with an `AgentConfig` built like `runner._build_agent_config` (non-streaming,
  logged, per-task `runs_dir`). Pull tokens from `config.token_usage.session`
  and tool stats from `tool_calls.jsonl`. *Decision:* run ci2lab **in-process**
  for the richest telemetry, but **also** capture subprocess wall-clock via the
  CLI in a calibration pass so latency is comparable to the shelled-out tools
  (see §5.5).
- **`claude-code`:** subprocess `claude -p "<prompt>" --output-format json
  --permission-mode acceptEdits` with `cwd=workspace`. Parse the JSON result for
  `usage`, `total_cost_usd`, `num_turns`, `duration_ms`. Pin the CLI version and
  model (`--model`). Confirm exact flags against the installed version during
  spike (§6, step 6).
- **`codex`:** subprocess `codex exec "<prompt>" --json --cd <workspace>
  --model <m> --sandbox workspace-write`. Parse JSONL events for token usage and
  completion. Pin version + model. Confirm flags during spike.

> Adapters must be **config-only to add**, mirroring ci2lab's own backend
> philosophy. New competitor → one adapter class, registered in an adapter
> registry. No changes to tasks, verifier, or runner.

### 5.2 Task spec (`BenchTask`, separate from `EvalTask`)

Define a new `BenchTask` in `ci2lab/bench/task.py` rather than mutating the
test-suite's `EvalTask` (decision §7.5 — benchmarks ≠ tests). It reuses the
fixture/workspace helpers from `ci2lab/evals` but carries the benchmark-specific
fields:

- `category: str` — `cli | qa | bug | feat | safety`.
- `prompt`, `workspace_setup` — as in `EvalTask` (the agent-visible task).
- `k_samples: int` — samples per condition (default from CLI; decision §7.3 ⇒ 5).
- `hidden_setup: dict` — files written into the workspace **after** the agent
  stops, before grading (the oracle tests). Same shape as `workspace_setup`.
- `verifier: dict` — `{command, expect_exit, fail_to_pass, pass_to_pass,
  forbid_paths}`. This is the functional-correctness oracle.
- `git_fixture: str | None` — path/template for tasks that need a seeded repo
  with a pinned initial commit (BUG-*).

### 5.3 Verifier (functional-correctness oracle)

A standalone step run **after** the adapter returns and **after** `hidden_setup`
injection:

1. If `forbid_paths` set, fail if `git diff --name-only` touches them (e.g. the
   agent edited `tests/`).
2. Run `verifier.command` in the workspace; capture exit code, stdout, stderr.
3. For bug tasks, run FAIL_TO_PASS and PASS_TO_PASS as separate invocations;
   `solved = FAIL_TO_PASS pass AND PASS_TO_PASS pass`.
4. Hard timeout; a hanging test ⇒ `solved=False`, status `timeout`.

Exit-code grading means **no LLM judge** for the core suite → no evaluator bias.

### 5.4 Environment reset (between every run)

Isolation is per (task, agent, sample). The existing runner already creates
`results_dir/workspaces/<id>`; generalize to
`workspaces/<agent>/<task>/<sample>`. For repo tasks:

- Provision from a pinned template/commit; before each sample run
  `git reset --hard <pin> && git clean -fdx`.
- Never reuse a workspace across samples (no carry-over state, caches, or
  half-applied patches).
- No network for fixtures; pin `pytest` and any fixture deps in a locked venv.

### 5.5 Normalization controls (fairness matrix)

Hold constant across all three systems, and **record** in `summary.json`:

| Knob | Policy |
| --- | --- |
| Prompt | **Byte-identical** per task; no per-agent tuning. |
| Auth | H1 competitors via **subscription** (Codex: Sign in with ChatGPT; Claude Code: `/login`) — no API key; ci2lab local. H2 Codex via `--oss`/custom provider on M. Record plan tier. |
| Model | H1: each system's documented subscription default. H2: the **same self-hosted open model M** (`qwen2.5-coder:32b`, §5.7) for ci2lab and Codex (Claude Code is H1-only). Record exact id/digest. |
| Temperature / seed | `temperature=0` for correctness runs; fixed seed where supported. |
| Context window | Cap to a common ceiling where configurable (`ci2lab` via `context_length`/`CI2LAB_NUM_CTX`; Claude/Codex via their flags). Record the effective window. |
| Round/step budget | Common `max_rounds` / max-steps cap. |
| Tool permissions | Auto-approve edits inside the workspace (`--yes` / `acceptEdits` / `workspace-write`); **never** auto-approve outside it. |
| Wall-clock cap | Common per-task timeout; exceed ⇒ `timeout` fail. |
| Versions | Pin and log ci2lab commit, `claude` CLI version, `codex` CLI version. |
| Warm-up | One discarded warm-up run per (agent, model) before timed runs. |

### 5.6 Runner & CLI — kept separate from the test/eval suite

Per decision §7.5, **benchmarks are not tests** and live apart from them:

| Concern | Location | Rationale |
| --- | --- | --- |
| Benchmark **code** (adapters, verifier, runner, metrics) | `ci2lab/bench/` (new package, sibling to `ci2lab/evals/`) | Product code stays in the package ([`CLAUDE.md`](../CLAUDE.md)); subject to ruff/mypy/pytest. |
| Benchmark **task specs** + fixtures | `benchmarks/tasks/*.json` (repo root) | Mirrors how `evals/tasks/` sits at root; clearly *not* a test. |
| Benchmark **results** (heavy, live) | `benchmarks/results/` | Git-ignored data, like other scratch/data. |
| Price table | `benchmarks/prices.json` | Versioned input to the cost metric. |

Why separate from `evals/`: the existing `evals/` runs **mock-first and
deterministic** — it is effectively a behavioural *test* of the harness, run in
CI. The benchmark is **live-only, comparative, and expensive** — it *quantifies
performance*, it does not gate the build. Conflating them would either make CI
pay API costs or dilute the benchmark with mock runs.

Don't reuse `run_eval_suite`; add a sibling runner in `ci2lab/bench/` that
iterates `task × agent × sample`, delegating execution to the adapter and
grading to the verifier. Give it its own CLI verb so the separation is visible:

```
ci2lab bench run --live \
  --agent ci2lab --agent ci2lab-multi --agent claude-code --agent codex \
  --model qwen2.5-coder:32b \
  --samples 5 --tasks-dir benchmarks/tasks
```

Keep runs **sequential** for the timed/local arms (a single local model owns the
VRAM; parallelism would distort latency and cause GPU contention). Hosted-only
arms may parallelize, but keep the default sequential for clean numbers.

### 5.7 Hardware and the shared model M

All runs execute on one workstation: **AMD Threadripper PRO 7975WX (32c/64t),
128 GB RAM, NVIDIA RTX A6000 (48 GB VRAM), Linux.** ci2lab's profiler reports a
GPU inference budget of **~44.6 GB VRAM** (`hardware_tier: enterprise`).

**Shared model M = `qwen2.5-coder:32b`** (Qwen2.5-Coder-32B-Instruct, served by
Ollama). Why this model:

- **Strongest open coding/agentic model that fits the A6000 with room to
  spare.** At Ollama's default Q4_K_M (~20 GB of weights) it leaves ~24 GB for
  the KV cache / context window — essential for multi-round agentic tasks that
  pull file contents into context. (The card can also hold Q5/Q6, ~24–28 GB, for
  higher fidelity at the cost of context room — see the open quantization
  question in §7.) A 70B model would not leave usable context headroom on a
  single 48 GB card, so it is out.
- **Native tool / function calling**, so it drives ci2lab's `native` tool mode
  and Codex's tool loop directly.
- **Runnable by both harnesses with no extra infra:** ci2lab via Ollama
  (`model: qwen2.5-coder:32b`); Codex via `codex --oss` (also Ollama-backed).
  This is exactly why Codex — not Claude Code — carries the H2 same-model arm.
- **Config-only to swap:** if a newer strong coder that fits 48 GB is in your
  Ollama, point both harnesses at it instead.

Pin the exact Ollama **digest** in `benchmarks/ENVIRONMENT.md`, and set a
generous `num_ctx` (ci2lab drives Ollama's native `num_ctx`; raise it via
`context_length`/`CI2LAB_NUM_CTX`) so long agentic transcripts aren't truncated.

---

## 6. Execution roadmap — get a pipeline running this week

Ordered, dependency-respecting checklist. Each step keeps the tree green
(`ruff`, `mypy ci2lab`, `pytest -q`) per [`CLAUDE.md`](../CLAUDE.md). Steps 1–7
are the "operational this week" core; 8–10 are the full matrix + write-up.

**Day 1 — Scaffold + schema**
1. [ ] Create the `ci2lab/bench/` package and the `benchmarks/` tree
       (`tasks/`, `results/` git-ignored). Record the environment matrix
       (ci2lab commit, Ollama model+digest, `claude`/`codex` CLI versions,
       hosted-model snapshot ids, hardware) in `benchmarks/ENVIRONMENT.md`, and
       seed `benchmarks/prices.json` with dated per-token prices.
2. [ ] Define `BenchTask` in `ci2lab/bench/task.py` — its own spec
       (`category`, `k_samples`, `hidden_setup`, `verifier`, `git_fixture`, plus
       the existing prompt/`workspace_setup` fields). **Reuse** `evals`' fixture
       helpers (`setup_workspace`, JSONL log readers) but **do not mutate
       `EvalTask`** — the test-suite schema stays stable (decision §7.5).
3. [ ] Add the consistency/unit tests for `BenchTask` loading under `tests/`
       (schema only — no execution behaviour yet). Keep ruff/mypy/pytest green.

**Day 2 — Tasks + oracle**
4. [ ] Author the 7 task fixtures under `benchmarks/tasks/*.json` with their
       `hidden_setup` test files and `verifier` blocks (CLI-01, CLI-02, QA-01,
       QA-02, BUG-01, BUG-02, FEAT-01). Hand-verify each oracle: the intended
       fix passes, an empty/no-op run fails.
5. [ ] Implement the **verifier** module (exit-code oracle, FAIL/PASS_TO_PASS,
       `forbid_paths` git check, timeout). Unit-test it against a known-good and
       known-bad patch without any agent in the loop.

**Day 3 — ci2lab adapters end-to-end**
6. [ ] Define `AgentAdapter` + `RunResult`; implement the **ci2lab adapter**
       (wrap `run_agent`, read `config.token_usage` + `tool_calls.jsonl`) and the
       separate **`ci2lab-multi`** adapter (`run_multi_agent`) — they are
       **distinct conditions** (decision §7.4). Wire the `bench` runner
       (`task × agent × sample`), metrics capture (latency timer, token
       extraction), and token→USD via `prices.json`.
       **Milestone: full pipeline green on both ci2lab conditions, live.**

**Day 4 — Competitor adapters (auth spike + integrate)**
7. [ ] **Auth + telemetry spike (do first):** confirm both CLIs run **headless
       under subscription** and emit token telemetry —
       `claude -p "<task>" --output-format json` (read `usage` + `total_cost_usd`)
       and `codex exec --json "<task>"`. Then implement both adapters parsing
       those fields, with `cwd=workspace` and pinned CLI versions.
       **Milestone: 1 task × 4 conditions × 1 sample produces a results row each.**

**Day 5 — Reset, H2 model, scale, report**
8. [ ] Implement git-based env reset + the normalization controls (§5.5) + the
       warm-up pass + inter-sample backoff (subscription rate limits, §2.5).
9. [ ] **Stand up the shared open model M** (Ollama/vLLM); smoke-test ci2lab on M
       and **`codex --oss`/custom-provider on M** (`codex exec --json` completes
       + emits token usage). Then run the matrix: **H1** (Claude Code + Codex
       under subscription + local ci2lab) + **H2** (ci2lab vs Codex on M) +
       **H3** (ci2lab single vs multi on M), 7 tasks × conditions × k=5, paced
       for rate limits. No Claude Code proxy, no model ladder (deferred).
10. [ ] Aggregate (`summary.json` with bootstrap CIs), generate the results
        table + plots, and draft the threats-to-validity section. Freeze the
        protocol for the paper.

**Definition of "operational this week":** steps 1–7 done ⇒ the harness can run
any task against any of the three agents, grade by hidden tests, and emit a
results row with correctness + tokens + latency. Steps 8–10 turn that into the
paper's dataset.

---

## 7. Decisions

### Locked (2026-06-29)

1. **Scope = H1 + H2 + H3, at zero API cost.** Competitors run under existing
   **Codex/Claude Code subscriptions** (no API key); ci2lab and the shared H2
   model run locally. H1 = as-shipped product comparison; **H2 = ci2lab vs Codex
   on one self-hosted open model M** (`qwen2.5-coder:32b`; the harness-
   isolation result); H3 = ci2lab single vs multi on M (confound-free control).
   **Claude Code is excluded from H2** (H1 only) — its subscription only drives
   its own harness and an open-model proxy is fragile. The **model ladder is
   deferred** (not in the first pass). See §0, §2.5.
2. **Cost = tokens, converted to USD.** Measure tokens uniformly; derive USD
   from a single dated price table; for local ci2lab runs the USD is an
   *imputed* hosted-rate figure, always labeled, with raw tokens shown (§4.2).
3. **k = 5** samples per (task, condition); report Pass@1 and Pass@5 with
   bootstrap CIs.
4. **ci2lab single-agent and multi-agent are separate conditions.** The
   `run_agent` vs `run_multi_agent` delta on our own stack is itself a result.
5. **Benchmarks are separated from tests.** Code in `ci2lab/bench/`, tasks in
   `benchmarks/tasks/`, results in `benchmarks/results/`, a distinct
   `ci2lab bench run` verb. The mock-first `evals/` suite stays as the
   build-gating behavioural test; the benchmark quantifies performance and never
   gates CI (§5.6).
6. **Hardware + shared model M fixed.** All runs on the A6000 workstation;
   **M = `qwen2.5-coder:32b`** (§5.7). The **model ladder is deferred** — not in
   the first pass.

### Still open

- **Include `SEC-01` safety task?** Cheap (existing security grading) and a
  local-first differentiator. Recommend including as a **secondary** axis, not a
  primary correctness number.
- **The exact quantization of M** (default Q4_K_M vs a higher Q5/Q6 the A6000
  can also hold) — pick during the Day-5 model bring-up; record the digest.

---

## 8. From benchmark to paper

### 8.1 The claim to make (and the one to avoid)

Do **not** lead with "ci2lab beats Claude Code." On raw H1 correctness a local
open model will usually trail frontier models, and a reviewer will dismiss the
paper as an unfair comparison. Lead instead with two defensible claims:

- **Efficiency frontier:** a local-first, open-model agent reaches *X%* of
  frontier Pass@1 at a small fraction of the tokens/cost and with no data
  leaving the machine — quantified, not asserted.
- **Harness contribution (H2):** with the model held fixed (ci2lab vs Codex on
  one open model M), the orchestration delta is *Z* — how much our
  ReAct/multi-agent design adds (or costs) independent of the underlying model.
  This is the scientific result and the reason H2 exists.

The multi-agent-vs-single-agent contrast on our **own** stack (decision §7.4) is
a clean secondary contribution: it isolates the value of orchestration without
any competitor confound at all.

### 8.2 Suggested structure

1. **Abstract** — local-first agent; controlled harness-isolation; headline
   efficiency + harness numbers with CIs.
2. **Introduction** — why local-first (privacy, cost, offline, reproducibility);
   the gap: existing agent benchmarks compare *whole products* and conflate
   model with harness.
3. **Related work** — Terminal-Bench, SWE-bench / **SWE-bench Verified**,
   SWE-agent, HumanEval (`pass@k`), AgentBench, τ-bench, GAIA. Position ours as
   *lightweight, local, harness-controlled* — not a replacement for those.
4. **Methodology** — task taxonomy (§3), metrics (§4), harness + normalization
   (§5), the H1/H2 design (§0). Emphasize the exit-code oracle and identical
   prompts.
5. **Threats to validity** — lift §2 wholesale; this section is a feature, not
   an apology. Model asymmetry, non-determinism, oracle integrity, small-N.
6. **Results** — H1 system-level table (as-shipped, under subscription:
   ci2lab vs Claude Code vs Codex); H2 harness-isolated (ci2lab vs Codex on the
   shared open model M); H3 single- vs multi-agent
   control; the efficiency-frontier plot (Pass@1 vs tokens/$); per-task
   breakdown; failure attribution (wrong vs stalled vs crashed). State the two
   honesty points: Claude Code can't join H2 for free (subscription drives only
   its own harness), and Codex on a non-native open model may understate its true
   harness quality.
7. **Discussion / Limitations** — what the numbers do and don't support;
   N=7 caveats; single-hardware caveat.
8. **Reproducibility / Artifact** — release tasks, fixtures, adapters, pinned
   versions, `prices.json`, raw `results.jsonl`, seeds. Aim for a runnable
   artifact.
9. **Conclusion.**

### 8.3 Rigor that will survive review

- **Pre-register the protocol.** Freeze this document (and the task set) *before*
  running the full matrix; report exactly the metrics defined here. No
  post-hoc task selection — that is the difference between a benchmark and a
  cherry-pick.
- **Avoid data contamination.** Hand-author all tasks; do **not** reuse public
  SWE-bench/Terminal-Bench instances whose solutions may be in the models'
  training data. Note this explicitly — it is a genuine advantage of a
  small bespoke suite.
- **Report CIs and effect sizes,** not point estimates; show per-task results so
  one easy/hard task can't swing the story.
- **Scope the claims to the suite.** With N=7, say "on this suite" — don't
  generalize to "all agentic tasks."
- **Venue fit.** Sized for an LLM-agents/SE workshop or an arXiv preprint, or as
  the evaluation chapter of a thesis/internal report. Don't oversell it as a
  general benchmark.

### 8.4 Division of labor with this harness

The harness produces `results.jsonl` + `summary.json` (with CIs) and the plots;
those drop straight into §6 (Results) of the paper. Methodology prose comes from
§§2–5 here. That means **once the matrix runs, ~half the paper is already
written** — which is the point of investing in the harness first.

---

*Cross-references:* request flow and module map in
[`docs/STRUCTURE.md`](STRUCTURE.md); quality gates and invariants in
[`CLAUDE.md`](../CLAUDE.md). Existing eval code: `ci2lab/evals/`
(`task.py`, `runner.py`, `run.py`); token accounting:
`ci2lab/harness/token_usage.py`; run logs: `ci2lab/harness/run_logger.py`.
