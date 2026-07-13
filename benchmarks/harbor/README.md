# benchmarks/harbor/ — ci2lab on Terminal-Bench

Run **ci2lab** as a custom agent inside **Terminal-Bench 2.x** (the *Harbor*
harness) so it is graded by a neutral third party on public tasks, and compared
**same-model** against `opencode` and `deepagents`. This is the external-validity
arm of the benchmark plan (Solution A / "Option A"); it complements — does not
replace — the private suite under [`benchmarks/tasks/`](../tasks/) and the
in-process comparison under [`ci2lab/bench/`](../../ci2lab/bench/).

Methodology and paper framing: [`docs/BENCHMARKING.md`](../../docs/BENCHMARKING.md).

## What's here

| File | Role |
| --- | --- |
| `ci2lab_harbor.py` | `Ci2LabAgent` / `Ci2LabMultiAgent` — Harbor `BaseInstalledAgent` subclasses. Thin: it imports `harbor` and delegates all logic to `ci2lab.bench.harbor`. |
| `pyproject.toml` | Editable-install shim so `--agent ci2lab_harbor:Ci2LabAgent` resolves. |
| `ci2lab.bench.harbor` *(in the package)* | The tested logic: run-command builder, local-model env, and token readback. |

The `Ci2LabMultiAgent` class is the single-vs-multi (H3) control — it is the same
agent with `--multi-agent`, so you get that comparison for free.

## Model M

Default **M = `qwen3-coder:30b`** (Qwen3-Coder-30B-A3B): native tool calling
(confirmed `tools` capability on Ollama), ~19 GB at Q4_K_M so it fits the A6000
with large KV headroom, and MoE (3.3B active) so it decodes several times faster
than a dense 32B — which keeps a multi-hour suite × three agents tractable. It is
already in [`ci2lab/catalog/models.json`](../../ci2lab/catalog/models.json) as
`tool_mode: native`. Override the model per run via `ci2lab.bench.harbor`
constants or `CI2LAB_MODEL` (see below).

> **Before a full run, smoke-test tool calling.** "Native in Ollama" can still
> fail for chat-template reasons. Drive a few `ci2lab --tool-mode native` tasks on
> M and confirm the dropped/mis-formatted tool-call rate is ~0 before spending
> hours on a suite — a model that mis-formats tool calls fails tasks for the
> wrong reason.

## One-time setup (on the A6000 host)

```bash
# 1) Harbor (Python >= 3.12) + Docker running
uv tool install harbor          # or: pip install harbor

# 2) ci2lab importable in the same env as harbor, and this shim on the path
pip install ci2lab              # or, from the repo root: pip install -e .
uv pip install -e benchmarks/harbor   # or export PYTHONPATH=benchmarks/harbor

# 3) local model server: Ollama serving M, reachable from a container
ollama pull qwen3-coder:30b
# ensure the daemon listens on all interfaces so containers can reach it:
#   OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Sanity-check the harness itself with the reference solution before touching
ci2lab:

```bash
harbor run -d terminal-bench@2.1 -a oracle          # should score ~100%
```

## Run the same-model matrix

Hold `-d` (dataset), the **model**, and `-k` (attempts) identical across all four
conditions. `--allow-agent-host host.docker.internal` lets the container reach
the host's Ollama.

```bash
D=terminal-bench@2.1

# ci2lab single-agent
harbor run -d $D --agent ci2lab_harbor:Ci2LabAgent \
  --allow-agent-host host.docker.internal \
  -k 5 -o jobs/ci2lab

# ci2lab multi-agent (H3 control)
harbor run -d $D --agent ci2lab_harbor:Ci2LabMultiAgent \
  --allow-agent-host host.docker.internal \
  -k 5 -o jobs/ci2lab-multi

# deepagents on the same local model (Harbor's langgraph adapter)
harbor run -d $D --agent langgraph \
  --agent-kwarg project_path=deepagents_harbor/langgraph_project \
  --agent-kwarg config=langgraph.json --agent-kwarg graph=deepagent \
  --model ollama:qwen3-coder:30b \
  --agent-env OLLAMA_HOST=http://host.docker.internal:11434 \
  -k 5 -o jobs/deepagents

# opencode on the same local model (needs an OpenAI-compatible provider config
# injected into the container — fork opencode-setup to drop ~/.config/opencode
# pointing at http://host.docker.internal:11434/v1 — then:)
harbor run -d $D -a opencode --model ollama/qwen3-coder:30b \
  --allow-agent-host host.docker.internal \
  -k 5 -o jobs/opencode
```

The frontier leaderboard numbers (e.g. opencode+Opus, deepagents+GPT-Codex) are
**cited context**, not runs you pay for; the defensible result is the same-model,
local, third-party-graded delta between these four.

## Read the results

- `harbor run` writes per-trial `results.json` and a job-root aggregate under
  `-o` (`jobs/<condition>/`). The **leaderboard-comparable score is `pass@1`** =
  `pass_at_k[1]` in the job aggregate. Run the whole dataset (no task filter) for
  a comparable number.
- **Tokens:** Harbor logs zero tokens for installed agents, so `Ci2LabAgent`
  recovers the real counts from ci2lab's own `run_summary.json` in
  `populate_context_post_run` and writes them onto the trial's `AgentContext`
  (`n_input_tokens` / `n_output_tokens`, plus `ci2lab_rounds` / `ci2lab_status`
  in metadata). Report **tokens per solved task** from there — the efficiency
  metric where a lean local harness can win even when raw pass@1 trails.

## A6000 sizing

Terminal-Bench task containers are CPU/Docker; the **A6000 is the model server**,
so a single 32B-class model serializes real agent concurrency to ~1–2 regardless
of `-n/--n-concurrent`. The full 89-task `terminal-bench@2.1` on a local model is
order **tens of hours per condition**. Practical options:

- Pre-register a **fixed subset** stratified across TB's task categories and
  report exactly that (never post-hoc select). Filter with
  `--include-task-name` / `--exclude-task-name` / `--n-tasks`, or a single task
  with `--task`.
- Cap per-task time with the task's timeout; a stuck agent fails closed.
- The MoE M keeps this feasible; a dense 32B roughly triples wall-clock.

## The one integration assumption to confirm on the first smoke run

The agent runs ci2lab in the container's **`/app`** (override with
`--agent-kwarg workdir=/some/dir`) and writes its run log to **`/logs/agent/`**,
which is expected to map back to the host `logs_dir` that Harbor mounts. On the
first single-task run, verify (a) ci2lab's edits landed in the graded directory
and (b) a `run_summary.json` appeared under the job's log dir so token readback
works. Adjust `workdir` / the log path in `ci2lab.bench.harbor` if a dataset
differs.

## One dataset, many benchmarks

The same adapter runs the TB registry by changing only `-d`: `terminal-bench@2.1`
(primary, contamination-resistant by construction), `swebench-verified`
(official grading via TB; cite with a contamination caveat), `appworld`,
`deveval`, `evoeval`. Confirm exact dataset slugs with `harbor dataset --help`.
