# Benchmark design: what we measure, and why each benchmark is there

This document explains **which benchmarks ci2lab runs, why each one earns its
place, what the results tables will look like, and exactly what each number
means**. It is the design rationale; [`BENCHMARKING.md`](BENCHMARKING.md) is the
methodology and [`benchmarks/harbor/`](../benchmarks/harbor/) is the run guide.

The central claim under test is **H2: at a fixed open model, the *harness* — not
the model — accounts for a measurable share of agentic capability.** Every choice
below follows from the need to make that claim falsifiable.

---

## 1. The four benchmarks, and the job each one does

No single benchmark can support the claim. Each covers a specific weakness of the
others.

| # | Benchmark | What it grades | Why it is here | Contamination |
| --- | --- | --- | --- | --- |
| **B1** | **Terminal-Bench 2.1** (via Harbor) | Binary pass/fail on the container's **final state**, 89 hand-authored tasks | **External validity.** Public, third-party-graded, tasks we did not author. Neutralises the "you tuned to your own suite" objection. | Resistant *by construction* (hand-authored, hidden outcome tests), not by secrecy |
| **B2** | **Internal suite** (`benchmarks/tasks/`) | Pass rate + tokens + latency on 7 private tasks | **Control.** Leak-proof, fast, and the only place we can author tasks that probe specific harness mechanisms. | Private (never published) |
| **B3** | **Tool-Call Correctness** (this repo's instrumentation) | Per-tool-call correctness, computed from run traces | **Mechanism isolation.** B1/B2 fuse tool-calling with reasoning and planning; this separates them. **This is the KPI you asked for.** | N/A — derived from our own runs |
| **B4** | **SWE-bench Verified** (via Harbor registry) | Official SWE-bench grading script | **Recognition.** A number reviewers already know how to read. | ⚠️ Known exposure — reported as secondary, with a caveat |

**Why there is no BFCL arm.** BFCL is the obvious candidate for a tool-calling
benchmark, and we deliberately do **not** run it. BFCL **supplies its own harness**:
the agent loop, the system prompt, the parser, and a hard-coded 20-step cap.
Running ci2lab "on BFCL" would measure *BFCL's* scaffolding wrapped around our
model, which is the opposite of the question we are asking. BFCL holds the harness
fixed and varies the model; H2 needs the transpose. It remains the right citation
for tool-calling *metric definitions* (§4) — just not a benchmark we execute.

**Why B3 had to be built.** B1, B2 and B4 all grade *outcomes*. A task fails
identically whether the model reasoned badly or simply emitted a malformed JSON
tool call. For a harness paper that is fatal: parsing, schema presentation, repair
and retry are *exactly* what a harness does, and an outcome-only benchmark cannot
see them. Nothing off-the-shelf fills this gap (§4), so we instrument it.

---

## 2. The KPI: tool-call correctness

> **"Percentage of the time a tool was correctly called."**

That sentence is under-specified as a metric, and a reviewer will say so. We
decompose it into a **ladder**, using the accepted terminology from the
function-calling literature (BFCL, Gorilla, Azure/DeepEval evaluator suites), and
report every rung.

### 2.1 The denominator is the whole ballgame

An **attempt** is *any* point at which the model tried to call a tool — including
attempts that never executed:

- a payload the parser could not read (**malformed**), and
- a call naming a tool that does not exist (**hallucinated tool**).

These two are the failure modes small local models hit most, and both used to
leave **no trace at all** in ci2lab's logs — they never reached the tool executor,
so they produced zero rows. Computing a rate over "calls that survived parsing"
would have quietly excluded the failures and reported a flattering number. Closing
that hole is what [`harness/run_logger.py`](../ci2lab/harness/run_logger.py)'s
`record_parse_failure` and
[`parsing_parts/resolver.py`](../ci2lab/harness/parsing_parts/resolver.py)'s
`detect_unknown_tool_attempt` exist for.

### 2.2 The ladder

Definitions live in [`ci2lab/harness/tool_metrics.py`](../ci2lab/harness/tool_metrics.py).

We adopt the granularity vocabulary from the agent-evaluation survey (arXiv
2503.16416), which names three levels: **Stepwise Evaluation**, **Trajectory-Based
Assessment**, and **Final Response Evaluation**. B1/B2/B4 are Final Response. **B3
is Stepwise** — the level at which a harness actually operates. We also adopt
**Gorilla's distinction**, the cleanest in the literature: a **hallucination** is
*invoking an entirely imagined tool*, which is "distinct from invoking an API
incorrectly, which we instead define as an **error**." Our rungs 2 and 3/4 keep
those apart for exactly that reason.

| Rung | Metric | Definition | Whose fault is a failure? |
| --- | --- | --- | --- |
| 1 | **Schema / parse validity** | payload parsed at all | **Harness** (schema presentation, parser, repair) |
| 2 | **Tool-selection validity** | named tool exists (inverse: *hallucinated-tool rate*) | **Harness** (how tools are presented) |
| 3 | **Argument validity** | required params present, types usable | **Harness** (schema hiding, coercion) |
| 4 | **Execution success** | the dispatched tool returned non-error | Joint harness/model/**environment** |

**Headline KPI — Tool-Call Correctness Rate (TCR):**

```
TCR = attempts that parsed AND named a real tool AND passed argument validation
      ─────────────────────────────────────────────────────────────────────────
      all tool-call attempts
```

Rung 4 is reported **separately**, not folded in: a `read_file` on a genuinely
missing file is an environment fact, not a tool-calling mistake.

### 2.3 Raw vs effective — the metric that carries the H2 claim

ci2lab **repairs** some malformed payloads (lenient JSON, argument coercion) and
runs them anyway. A repaired call is indistinguishable from a clean one in the
result — but only the clean one is a *model* success. So we report two rates:

- **Raw TCR** — what the model got right **unaided**.
- **Effective TCR** — what the harness ultimately **dispatched**.
- **Repair rate** = Effective − Raw = **what the scaffolding contributed.**

That gap is the single most direct evidence for "scaffolding, not fine-tuning":
same model, same weights, same prompt — and one harness converts a failed call
into a working one where another does not. `ToolCall.repaired` propagates it from
the parse site to the run log.

### 2.4 The trap we must not fall into

**TCR is denominator-gameable.** A timid harness that makes few, cautious tool
calls scores a high TCR by *doing less*. TCR is therefore **never reported alone**
— always beside **absolute tool-call count** and **end-to-end task success (B1)**.
A harness that wins on TCR while losing on pass@1 has not won.

---

## 3. Results tables

### Table 1 — Main result: harness effect at fixed model (H2)

All arms on **M = `qwen3-coder:30b`** (local, Ollama, native tool calling), same
dataset, same attempts `k`, same hardware. Marginal API cost: **zero**.

| Harness | pass@1 (TB-2.1) | Tool-call attempts | **Raw TCR** | **Effective TCR** | Repair rate | Hallucinated tool | Malformed | Invalid args | Tokens / solved task |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **ci2lab** (single) | _x.x % ± ci_ | _n_ | _x.x %_ | _x.x %_ | _x.x %_ | _x.x %_ | _x.x %_ | _x.x %_ | _n_ |
| **ci2lab** (multi) | | | | | | | | | |
| **opencode** | | | | | — † | | | | |
| **deepagents** | | | | | — † | | | | |

† opencode surfaces a malformed payload as an errored tool call rather than
repairing it, so its raw and effective TCR coincide and *repair rate is a
ci2lab-only column*. That asymmetry **is** the finding — but it is a difference in
scaffolding behaviour, not a like-for-like cell, and is labelled as such.

**How to read it.** pass@1 answers *did it work*; TCR answers *why*. A harness can
lose on pass@1 while winning on TCR (it calls tools correctly but plans badly), or
the reverse. The interesting cell is the **repair rate**: tokens the model got
wrong that ran anyway.

### Table 2 — Single vs multi-agent (H3)

Same columns as Table 1, restricted to the two ci2lab arms. Free: the multi-agent
condition is the same adapter with `--multi-agent`.

### Table 3 — Secondary / external

| Benchmark | ci2lab | opencode | deepagents | Note |
| --- | --- | --- | --- | --- |
| SWE-bench Verified (via TB) | | | | Official grader; contamination caveat |
| Internal suite (7 tasks) | | | | Private control |

Frontier leaderboard numbers (opencode + Opus ≈ 51.7 %, deepagents + GPT-Codex ≈
66.5 %) are **cited as context, not run** — they mark the ceiling a local 32B
cannot reach and are not part of any claim.

---

## 4. Why we built B3 instead of using an existing tool-calling benchmark

We surveyed the field before writing code.

| Benchmark | Isolates tool calls? | Why it does not fit |
| --- | --- | --- |
| **BFCL** (ICML 2025) | ✅ Yes — AST accuracy, hallucination detection | Evaluates the **model** with BFCL's **own fixed harness** (its own loop, prompt, parser, 20-step cap). Holds the harness constant, varies the model. **We need the transpose.** Cited for metric definitions; not run. |
| **T-Eval** (ACL 2024) | ✅ Yes — the strongest step-level isolation | Achieves it by feeding a **golden oracle prefix**, so the model never runs its own trajectory. Cannot evaluate a *harness* driving a real task. |
| **τ-bench** | ❌ No | Reward is **binary end-state** (DB hash + required outputs). Reports *no* per-tool-call metric. Good source for `pass^k`, not for tool calls. |
| **ToolBench / ToolAlpaca** | Partially | **LLM-as-judge**. We want a mechanical, reproducible count. |
| **ACEBench** (EMNLP 2025) | ✅ Partially | Reports Process Accuracy *and* End-to-End Accuracy side by side — **the precedent for our two-column design** — but only within its own Agent sandbox, on its own harness. |
| **Terminal-Bench** | ❌ No | Final container state only. |

**The honest novelty claim** — narrow, and defensible:

> No existing benchmark reports a **mechanical, trace-derived, per-tool-call
> correctness rate that is comparable across heterogeneous agent harnesses at a
> fixed model.**

**What we must NOT claim**, because it is false: that nobody studies harnesses.
Two works already do, and the paper must cite and differentiate from both:

- **Harness-Bench** (arXiv 2605.27922) — a factorial harness × model matrix. It
  has a "Tool Use" dimension, but it is an **LLM-judge rubric score**, not a
  mechanical count.
- **Holistic Agent Leaderboard (HAL)** (arXiv 2510.11977) — models × scaffolds ×
  benchmarks, via **LLM-aided log inspection**.

And the objection to pre-empt, not dodge: **ALE ("Does the Harness Matter?")
reports model choice moving pass rate ~18 pp vs. harness ~6 pp — roughly 3×
larger.** Our answer is not to dispute it but to scope it: *at a fixed open model
— the regime that matters when you cannot simply buy a frontier model — the
harness is the only lever available*, and its effect on **tool-call reliability**
specifically is larger than its effect on end-to-end pass rate. Table 1 is built
to show exactly that.

---

## 5. Fairness controls (the things that would silently rig the result)

These are confounds we found in the source, not hypotheticals.

1. **`num_ctx` asymmetry.** opencode talks to Ollama's OpenAI-compatible `/v1`,
   which **ignores `num_ctx`**; ci2lab uses Ollama's native API and **actually sets
   it**. Unequalised, ci2lab would silently get a larger effective context on
   identical hardware. **Control:** set the window **server-side** for everyone —
   `OLLAMA_CONTEXT_LENGTH=32768 ollama serve` — and pin every arm to that number.
2. **opencode auto-compaction.** An unlisted model defaults to `limit.context = 0`,
   which **disables compaction entirely**. **Control:** `opencode_local.json` sets
   it explicitly to the same window.
3. **opencode permissions.** Without `--dangerously-skip-permissions`, `run`
   **auto-rejects** every prompt and the agent silently does nothing. **Control:**
   the flag is set in the adapter.
4. **Frontier-tuned competitor scaffolds.** opencode and deepagents were built and
   tuned for frontier models; at 32B they will underuse their own tooling. This is
   the mirror image of our own Codex caveat, and is stated symmetrically — not
   quietly banked as a ci2lab win.
5. **Token accounting.** Harbor reports **zero tokens for all installed agents**.
   Every token figure comes from each agent's own trace, so ci2lab's counts are
   exact and competitors' are trace-derived. The asymmetry is disclosed.

---

## 6. Where each number comes from

| Number | Source |
| --- | --- |
| pass@1 | Harbor job aggregate `results.json` → `pass_at_k[1]` |
| ci2lab tokens + TCR | ci2lab `run_summary.json` → `token_usage`, `tool_call_quality` (read by [`bench/harbor.py`](../ci2lab/bench/harbor.py)) |
| opencode TCR | opencode `run --format json` NDJSON `tool_use` events (parsed by [`bench/opencode_trace.py`](../ci2lab/bench/opencode_trace.py)) |
| deepagents TCR | ⚠️ **Gap** — the `langgraph` adapter emits no trajectory. Requires writing an emitter before deepagents can appear in the TCR columns. |
| Confidence intervals | Bootstrap (already in `ci2lab/bench/`) |

**Known gap, stated plainly:** Harbor's ATIF trajectory format has **no
tool-error field**, and its opencode adapter discards opencode's `status`/`error`.
So ATIF is *not* a free cross-harness metric — which is why the KPI is computed
from each harness's **native** trace instead. deepagents currently emits neither,
so its TCR cells are blank until an emitter is written. That is a real limitation,
not a rounding error, and the table shows it as blank rather than guessing.
