# Model-selection pilot (pre-registered)

## Why

The first `terminal-bench@2.0` run on **M = `qwen3-coder:30b`** produced a **floor
effect**: pass@1 ≈ 0 with no spread. A benchmark on which every arm scores zero
cannot test H2 (ci2lab vs. competing harnesses at a fixed model) or H3 (single vs.
multi-agent), because it has no power to separate them.

TB 2.0 cannot be re-sampled out of this problem: of its 89 tasks only **4 are
`easy`** (55 medium, 30 hard). Selecting an easier subset would also mean picking
tasks *after* seeing which ones ci2lab failed — post-hoc selection, which is
exactly what the pre-registration in [`README.md`](README.md) exists to prevent.

The **model M is a free parameter of the protocol**, chosen before results and
stated in the paper. Choosing an M whose capability lands inside the benchmark's
dynamic range is *instrument selection*, and it leaves the third-party-graded
task set — the whole source of external validity — untouched. That is the lever
this pilot pulls.

## Selection rule (fixed BEFORE any pilot result is read)

Choose M on **resolution**, never on ranking:

1. M must score **strictly between 0 and 1** on the pilot set. A model at 0 cannot
   separate harnesses; a model at 1 cannot either.
2. Among models satisfying (1), prefer the one that is **tractable** on one A6000
   (a run of 30 tasks × 4 arms × k=3 must finish in available time).
3. **M is NOT chosen by which model makes ci2lab score highest.** Selecting the
   model that flatters the harness under test would bias the very comparison the
   benchmark exists to make.
4. Tool-call integrity is a gate, not a tiebreak: a model whose malformed/dropped
   tool-call rate is materially above 0 is rejected regardless of score, because
   it fails tasks for the wrong reason.

## Contamination control

The pilot runs **only on tasks outside the frozen 30** in
[`tasks_30.txt`](tasks_30.txt). The pre-registered subset stays unread until the
final matrix runs. All 4 `easy` tasks are outside the frozen set, so no easy task
is spent here that the main run would have used.

Pilot tasks (stage 1, all `easy`, k=1):

    cobol-modernization
    fix-git
    overfull-hbox
    prove-plus-comm

Stage 2 (only for models that clear stage 1) adds `medium` tasks from the free
pool to confirm the model is not saturated at the top of the range.

## Candidates

| Model | Size | `tool_mode` | Note |
| --- | --- | --- | --- |
| `qwen3-coder:30b` | 18 GB | native | incumbent M; floored on TB 2.0 |
| `qwen2.5-coder:32b` | 19 GB | native | dense 32B |
| `llama3.3:70b` | 42 GB | **fenced** | 42 GB on a 48 GB card — KV cache at 32k ctx may not fit; fenced parsing is a different code path, so its tool-call quality must be reported, not assumed |

Held constant across the pilot: harness (ci2lab single-agent), `max_rounds=100`,
`num_ctx=32768`, k=1, and the task set.

## Outcome

M was selected on the pre-registered rule: `qwen3-coder:30b` was the only
candidate with resolution (1/3 on the easy stage) and a clean tool-call rate
(1.00). `qwen2.5-coder:32b` was rejected by the integrity gate (raw tool-call
rate 0.5–0.75, malformed calls); `llama3.3:70b` passed nothing, ran through a
different (fenced) tool-call path, and was the slowest.

TB 2.0 nonetheless floored for the selected M (0/12 on the medium/hard frozen
set), which is a property of the benchmark, not the harness — so B1 moved to
**OpenThoughts-TBLite** (difficulty-calibrated, same format and grading). A
9-task calibration of M on held-out TBLite tasks (4 easy / 3 medium / 2 hard,
`max_rounds=100`, k=1) confirmed resolution:

| difficulty | pass@1 |
| --- | --- |
| easy | 2/4 |
| medium | 1/3 |
| hard | 1/2 |
| **overall** | **4/9 (0.44)** |

with **0 infrastructure errors** and a mean tool-call rate of 0.988. These 9
tasks are calibration only — they are excluded from the frozen run subset
([`tasks_tblite_30.txt`](tasks_tblite_30.txt)) and are not reported as results.
