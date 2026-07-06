# benchmarks/

Performance benchmark suite that compares the `ci2lab` harness against OpenAI
Codex CLI and Claude Code. **This is not the test suite** — tests (`tests/`,
`evals/`) check that the harness *works*; this measures how *well* it performs,
runs live, and never gates CI. Full methodology:
[`docs/BENCHMARKING.md`](../docs/BENCHMARKING.md).

## Layout

```
benchmarks/
  tasks/         versioned task definitions (*.json) — the agent-visible prompt,
                 fixtures, hidden oracle tests, and verifier blocks
  results/       run artifacts (git-ignored): workspaces, run logs, results.jsonl,
                 summary.json
  prices.json    per-million-token USD price table (cost is derived from tokens)
  ENVIRONMENT.md the pinned hardware / model / CLI versions for a run
```

The harness code lives in the package at [`ci2lab/bench/`](../ci2lab/bench/).

## Running

Benchmarks run **live** (local Ollama for ci2lab; Codex/Claude Code under their
subscriptions). They are never run by `pytest`.

### Quick start (all-local: H2 + H3, two commands)

`ci2lab`, `ci2lab-multi` and Codex all run on the same local model M, so one
command produces the ci2lab-vs-Codex (H2) and single-vs-multi (H3) comparison;
the second prints the tables and flags anything untrustworthy:

```bash
# 1) run ci2lab (single + multi) and Codex, all on the shared local model M
BENCH_CODEX_OSS=1 ci2lab bench run \
  --agent ci2lab --agent ci2lab-multi --agent codex \
  --model qwen2.5-coder:32b --samples 5

# 2) aggregate every run so far into comparison tables + a validity report
ci2lab bench report
```

Add the H1 frontier competitors (their own subscription models) whenever you
want, then re-run `ci2lab bench report`:

```bash
ci2lab bench run --agent claude-code --model sonnet   --samples 5
ci2lab bench run --agent codex       --model <gpt-id> --samples 5   # no BENCH_CODEX_OSS
```

### More examples

```bash
# ci2lab only (single + multi agent), shared local model:
ci2lab bench run --agent ci2lab --agent ci2lab-multi \
  --model qwen2.5-coder:32b --samples 5

# H3 smoke: local single-agent vs local multi-agent on the same small task set:
ci2lab bench run \
  --tasks-dir benchmarks/tasks/h3_smoke \
  --results-dir benchmarks/results/h3_smoke \
  --agent ci2lab --agent ci2lab-multi \
  --model qwen2.5-coder:32b --samples 1

# Full matrix once the competitor CLIs are configured (see docs §6):
ci2lab bench run \
  --agent ci2lab --agent ci2lab-multi --agent claude-code --agent codex \
  --model qwen2.5-coder:32b --samples 5

# A subset of tasks:
ci2lab bench run --agent ci2lab --task cli-01 --task bug-01

# Equivalent module form:
python -m ci2lab.bench.run --agent ci2lab
```

Results land in `benchmarks/results/<timestamp>/` as `results.jsonl` (one row per
task × agent × sample) and `summary.json` (per task × agent: Pass@1, Pass@k,
mean tokens, imputed USD, median latency).

After every run, an aggregate Excel report is regenerated at
`benchmarks/results/benchmark_report.xlsx` from **all valid runs** under the
results dir (infrastructure-error / timeout runs are excluded). It has four
sheets — README, Agent Comparison, Per Task × Agent, and All Runs — and groups by
`(agent, model)` so the same adapter on two models (e.g. Codex on the local model
for H2 vs a frontier model for H1) stays on separate rows. Report generation
never fails a run; a problem is logged and the run still exits `0`.

## Competitor CLI knobs (env vars)

The `codex` / `claude-code` adapters are driven entirely by env vars so any CLI
version works without editing code. Each run writes the exact command it ran to
`codex_cmd.txt` / `claude_cmd.txt` (and stderr to `*_stderr.txt`) in its run dir.

| Var | Effect |
| --- | --- |
| **`BENCH_CODEX_CMD`** | **Full command template** (guess-proof). Placeholders `{prompt}`/`{model}`/`{workspace}`; the harness runs it verbatim. If `{prompt}` is absent, the prompt is piped to stdin. Overrides all the built-in Codex flags below. |
| `BENCH_CODEX_OSS=1` | *(default path)* Add `--oss --local-provider ollama` to `codex exec` → route Codex at the local model M (H2). |
| `BENCH_CODEX_LOCAL_PROVIDER` | Local provider for `--oss` (default `ollama`; also `lmstudio`). Set empty to omit. |
| `BENCH_CODEX_ARGS` | Extra `codex` args before the prompt (default path only). |
| `BENCH_CODEX_BIN` | Path to the `codex` executable (default path only). |
| **`BENCH_CLAUDE_CMD`** | Full command template for Claude Code (same placeholders/semantics). |
| `BENCH_CLAUDE_ARGS` | Extra `claude` args before the prompt (default path only). |
| `BENCH_CLAUDE_BIN` | Path to the `claude` executable (default path only). |

**Recommended for Codex-on-M:** once you find a `codex exec …` command that works
against local Ollama by hand, set it as the template so the harness never guesses:

```bash
export BENCH_CODEX_CMD='codex exec --oss --local-provider ollama -m {model} --skip-git-repo-check --json {prompt}'
ci2lab bench run --agent codex --model qwen2.5-coder:32b --task cli-01 --samples 1
```

(`--skip-git-repo-check` is needed because benchmark workspaces are throwaway
dirs Codex would otherwise refuse to run in. The built-in default already
includes it, so plain `BENCH_CODEX_OSS=1` works too.)

**Codex + local model (H2):** `--oss` must attach to the `exec` subcommand
(`codex exec --oss …`), which the adapter now does. If your Codex still routes to
the ChatGPT account (a `"...not supported when using Codex with a ChatGPT
account"` error in `results.jsonl`), your version selects the local provider
differently — set it via `BENCH_CODEX_ARGS` (e.g. after configuring an Ollama
provider in `~/.codex/config.toml`, use `BENCH_CODEX_ARGS='-c model_provider=oss'`)
without touching code. Confirm with `codex exec --help | grep -i oss`.

## Task ids

| id | family | failure mode |
| --- | --- | --- |
| `cli-01` | CLI exec | large-file tool selection (grep vs read-all) |
| `cli-02` | CLI exec | run a script, diagnose the failing step |
| `qa-01`  | code Q&A | locate a symbol in an unseen repo |
| `qa-02`  | code Q&A | trace a value across files |
| `bug-01` | bug fix  | patch a failing unit test (single file) |
| `bug-02` | bug fix  | multi-file regression |
| `feat-01`| code gen | implement a stub to a hidden spec |
