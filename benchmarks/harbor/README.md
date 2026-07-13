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
pip install -e .                      # from the repo root
uv pip install -e benchmarks/harbor   # or export PYTHONPATH=benchmarks/harbor

# 3) Serve the ci2lab wheel to the task containers.
#    ci2lab is NOT on PyPI, so each container installs a wheel fetched from the
#    host. The wheel FILENAME pins the exact build under test — rebuild and bump
#    the version rather than overwriting a wheel mid-experiment.
python -m build --wheel               # -> dist/ci2lab-0.1.0-py3-none-any.whl
(cd dist && python -m http.server 8000 &)
#    Override the URL if needed: --agent-kwarg wheel_url=http://.../ci2lab-X.whl

# 4) Local model server: Ollama serving M, reachable from a container.
ollama pull qwen3-coder:30b
#    FAIRNESS CONTROL — set the context window SERVER-SIDE so every arm gets the
#    same one. opencode talks to /v1 and cannot set num_ctx; ci2lab can. Without
#    this, ci2lab silently gets a bigger effective context than its competitors.
OLLAMA_CONTEXT_LENGTH=32768 OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Sanity-check the harness itself with the reference solution before touching
ci2lab:

```bash
harbor run -d terminal-bench@2.1 -a oracle          # should score ~100%
```

## Pre-register the task subset (do this BEFORE any run)

One A6000 serializes the model, so the full 89-task suite across four arms is out
of reach. We run **30 tasks x 4 arms x k=3 attempts**. A subset is only honest if
it is fixed *before* results are seen — otherwise the task list itself becomes a
free parameter.

1. List the dataset's tasks and their categories (from `harbor`).
2. Freeze the sample deterministically and **commit the output**:

```python
from ci2lab.bench.task_sample import Task, stratified_sample

tasks = [Task(task_id, category) for task_id, category in ...]   # from step 1
subset = stratified_sample(tasks, 30, seed=20260710)             # record the seed
print("\n".join(t.task_id for t in subset))                      # -> tasks_30.txt
```

3. Pass that frozen list to every arm (identical for all four), e.g. one
   `--include-task-name` per id. **Never** regenerate it after seeing a result.

## Run the same-model matrix

Hold `-d` (dataset), the **model**, the **task subset**, and `-k` (attempts)
identical across all four conditions. `--allow-agent-host host.docker.internal`
lets the container reach the host's Ollama **and** the wheel server.

```bash
D=terminal-bench@2.1
# plus, on every command below: -k 3 and the frozen task list from tasks_30.txt

# ci2lab single-agent
harbor run -d $D --agent ci2lab_harbor:Ci2LabAgent \
  --allow-agent-host host.docker.internal \
  -k 5 -o jobs/ci2lab

# ci2lab multi-agent (H3 control)
harbor run -d $D --agent ci2lab_harbor:Ci2LabMultiAgent \
  --allow-agent-host host.docker.internal \
  -k 5 -o jobs/ci2lab-multi

# deepagents on the same local model.
# The local checkout (../deepagents-main) exposes DeepAgentsWrapper(BaseAgent),
# which resolves its model through LangChain's init_chat_model — so the model
# string is LangChain-format (`ollama:` prefix), NOT Harbor's `ollama/`.
# Put its package on the path first:
#   export PYTHONPATH=$PYTHONPATH:/path/to/deepagents-main/libs/evals
harbor run -d $D --agent deepagents_harbor:DeepAgentsWrapper \
  --model ollama:qwen3-coder:30b \
  --agent-env OLLAMA_HOST=http://host.docker.internal:11434 \
  --allow-agent-host host.docker.internal \
  -k 5 -o jobs/deepagents

# opencode on the same local model. Harbor's stock opencode agent cannot point at
# a local endpoint, so use our subclass, which injects the provider config:
harbor run -d $D --agent opencode_local:OpenCodeLocal \
  --model ollama/qwen3-coder:30b \
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
