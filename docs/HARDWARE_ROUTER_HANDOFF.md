# Handoff: Hardware profiler + Model router

> **For the AI / developer implementing this part.**
> The agentic harness is implemented by someone else. This document defines **what to build**, **what not to touch**, and **how to fit with the harness** at the end.

**Project root:** `Ci2Lab/IAmultiagentica/`
**Parent workspace:** `Ci2Lab/` (reference repos only, see `references/EXTERNAL_REPOS.md`)

---

## Implementation status

Summary of what **already exists** versus what is **missing** per this handoff.

| Component | Status | Files / CLI |
|-----------|--------|-------------|
| `hardware/profile.py` | Implemented | `scan_hardware()` — RAM, VRAM, GPU, CPU, inference budget |
| `router/catalog.py` | Implemented | Loads `ci2lab/catalog/models.json` (64 models) |
| `router/intent.py` | Implemented | Keyword classifier (`coding`, `reasoning`, `rag`, …) |
| `router/recommend.py` | Implemented | Scoring, `model_fits()`, download plan |
| `router/selection.py` | Implemented | `build_model_selection()` — **production path** |
| `router/resolve.py` | Optional | `resolve_model()` auto-picks; not used in chat/agent/UI |
| CLI `ci2lab hardware` | Implemented | Table or `--json` |
| CLI `ci2lab models recommend` | Implemented | With/without prompt; download plan |
| CLI `ci2lab models install` | Implemented | pull/run/chat commands |
| CLI `ci2lab models run` | Implemented | `ollama run` of the chosen tag |
| `pipeline.py` | Implemented | `prepare_session()`, `build_agent_config()` |
| `runtime/ensure.py` | Pending | No auto-pull or installed-model check |
| Hardware/router tests | Partial | `test_hardware_profile.py`, `test_cli_models.py` |

### What is left to close the handoff

1. **`ci2lab/runtime/ensure.py`** — `ensure_model_ready(selection)` with optional `ollama pull`.
2. **`prefer_installed` in `resolve_model()`** — or retire `resolve_model` if the user-chooses-the-model flow is confirmed.
3. **Per-model live validation** — only `llama3.1:8b` has been validated in the harness evals.

---

## 1. Project context

**IAmultiagentica** (the `ci2lab` Python package) is a local CLI that:

1. Detects the computer's capabilities (RAM, VRAM, GPU).
2. Interprets the user's intent (e.g. `"program really well"`).
3. Picks the best open-source model that **fits** that hardware.
4. (Optional) Downloads/starts the model via Ollama.
5. Hands control to the **agentic harness**, which runs the ReAct loop with tools.

```
┌─────────────────────────────────────────────────────────────┐
│  YOUR PART (this handoff)                                   │
│  hardware/  +  router/  +  runtime/ (ensure_model)          │
└───────────────────────────┬─────────────────────────────────┘
                            │  ModelSelection (contract)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  THE OTHER PERSON'S PART (harness)                          │
│  harness/  — ReAct loop, tools, prompts, permissions        │
└─────────────────────────────────────────────────────────────┘
```

**Golden rule:** do not import opencode, deepagents, odysseus, or claude-code as dependencies. Only consult the repos in `../` (see `references/EXTERNAL_REPOS.md`) and note extractions in `references/EXTRACTION_LOG.md`.

---

## 2. Scope: what is and is not yours

### Your responsibility

| Module | Description |
|--------|-------------|
| `IAmultiagentica/ci2lab/hardware/` | Scan RAM, VRAM, GPU, OS, inference mode (CPU/GPU) |
| `IAmultiagentica/ci2lab/router/` | Model catalog, intent classification, optimal selection |
| `IAmultiagentica/ci2lab/runtime/` | Check/download/start a model in Ollama (MVP) |
| `IAmultiagentica/ci2lab/catalog/` | JSON/YAML with real models (Mistral, Qwen, Llama, Gemma, NVIDIA) |
| CLI | `ci2lab hardware`, `ci2lab models recommend`, `ci2lab models pull` |
| Tests | `IAmultiagentica/tests/` — profiler, selector, VRAM edge cases |

### Out of your scope (harness)

- ReAct loop, tool-call parsing, bash/read/grep execution
- Agent system prompts, tool permissions
- `ci2lab/harness/` (except **consuming** `ModelSelection`)

### Shared contract (do NOT change without agreement)

File: **`IAmultiagentica/ci2lab/contracts/types.py`**

Both sides import only from there to integrate. If you need a new field, add it as optional and document it in that file.

---

## 3. Integration contract (the most important part)

### 3.1 Input you receive from the user

```python
user_prompt: str          # e.g. "program really well"
cwd: str | None = None    # working directory (optional)
force_model: str | None   # manual override (--model)
```

### 3.2 Output you must produce: `ModelSelection`

The harness will call:

```python
from ci2lab.contracts.types import ModelSelection, HardwareProfile

selection: ModelSelection = resolve_model(user_prompt, profile=profile)
# The harness uses:
#   selection.ollama_tag      → model to load
#   selection.backend_url     → http://localhost:11434/v1
#   selection.tool_mode       → "native" | "fenced"
#   selection.context_length  → for context trimming
```

**Required `ModelSelection` fields:** see `ci2lab/contracts/types.py`.

### 3.3 Public function you must expose

Implement in `ci2lab/router/resolve.py`:

```python
def resolve_model(
    user_prompt: str,
    *,
    profile: HardwareProfile | None = None,
    force_model_id: str | None = None,
    prefer_installed: bool = True,
) -> ModelSelection:
    """
    1. profile = profile or scan_hardware()
    2. intent = classify_intent(user_prompt)
    3. model = select_best_model(intent, profile, force_model_id)
    4. return ModelSelection with metadata for the harness
    """
```

### 3.4 Startup function (runtime)

Implement in `ci2lab/runtime/ensure.py`:

```python
def ensure_model_ready(selection: ModelSelection, *, pull: bool = True) -> None:
    """
    - Check whether Ollama has the tag
    - If pull=True and missing → ollama pull
    - Optional: warmup with a minimal prompt
    - Raise a clear RuntimeError if Ollama does not respond
    """
```

### 3.5 Unified pipeline (implemented)

In `ci2lab/pipeline.py`:

```python
def prepare_session(user_prompt, *, force_model=None, tool_mode_override=None, ...) -> tuple[HardwareProfile, ModelSelection]:
    profile = scan_hardware()
    selection = build_model_selection(force_model or DEFAULT_MODEL, tool_mode_override=..., profile=profile)
    return profile, selection

def build_agent_config(runtime: Ci2LabConfig, selection: ModelSelection, **overrides) -> AgentConfig:
    ...
```

The user chooses the model (`--model`, UI, or config). `resolve_model()` remains an optional API for future auto-selection.

The harness receives:

```python
from ci2lab.harness import run_agent

_, selection = prepare_session(prompt, force_model=runtime.model, ...)
config = build_agent_config(runtime, selection, session_id=...)
run_agent(prompt, selection, config=config)
```

---

## 4. Folder structure

See [`STRUCTURE.md`](STRUCTURE.md) for the up-to-date tree. Summary:

```text
ci2lab/
├── cli/              # parser, runtime, commands/*
├── pipeline.py       # prepare_session, build_agent_config
├── console.py        # shared Rich output
├── contracts/, hardware/, router/, runtime/, catalog/
├── security/         # permission engines
├── harness/
│   ├── query/        # run_agent (ReAct)
│   ├── context/, security/, tools/, mcp/, skills/
│   └── repl.py, session.py, …
├── evals/, ui/, scripts/
└── config.py
```

The reference repos are **outside**, in `Ci2Lab/claude-code-main/`, etc.

**Do not create** harness logic in `router/` or `hardware/`.

---

## 5. Hardware profiler

### 5.1 `HardwareProfile` (already defined in contracts)

Should be filled by each `scan_hardware()` (with an optional 60 s TTL cache).

### 5.2 What to detect

| Field | Windows | Linux | Notes |
|-------|---------|-------|-------|
| `ram_total_gb` | `psutil` | `psutil` | |
| `ram_available_gb` | `psutil` | `psutil` | |
| `vram_total_gb` | `nvidia-smi` | `nvidia-smi` | 0 if CPU only |
| `vram_available_gb` | `nvidia-smi` | `nvidia-smi` | estimate free |
| `gpu_name` | nvidia-smi / WMI | nvidia-smi | `"CPU only"` if no GPU |
| `gpu_vendor` | `nvidia` \| `amd` \| `intel` \| `none` | same | |
| `cpu_cores` | `psutil` | `psutil` | |
| `os` | `windows` \| `linux` \| `darwin` | | |
| `inference_mode` | `gpu` if VRAM≥4GB else `cpu` | same | |
| `inference_budget_gb` | see formula below | | |

### 5.3 `inference_budget_gb` formula

```text
If inference_mode == "gpu":
    inference_budget_gb = max(0, vram_available_gb - 2.0)
If inference_mode == "cpu":
    inference_budget_gb = max(0, ram_available_gb * 0.6)
```

### 5.4 CLI command

```bash
cd IAmultiagentica
ci2lab hardware
ci2lab hardware --json
```

### 5.5 Acceptance criteria

- [ ] On the target Windows machine it returns consistent RAM (±1 GB).
- [ ] If there is an NVIDIA GPU, it reports VRAM; otherwise `inference_mode=cpu` without crashing.
- [ ] `ci2lab hardware --json` is parseable by `json.loads`.

---

## 6. Model catalog

### 6.1 Data source

Convert the project table into **`ci2lab/catalog/models.json`**.

Each entry:

```json
{
  "id": "qwen2.5-coder-32b",
  "display_name": "Qwen2.5 Coder 32B",
  "family": "qwen",
  "categories": ["coding", "refactor", "analysis"],
  "params_b": 32,
  "active_params_b": 32,
  "vram_inference_gb": 22,
  "ram_inference_gb": 24,
  "vram_min_gb": 20,
  "ollama_tag": "qwen2.5-coder:32b",
  "hf_repo": "Qwen/Qwen2.5-Coder-32B-Instruct",
  "supports_tools": true,
  "tool_mode": "native",
  "context_length": 32768,
  "tier": "workstation",
  "benchmark_score": {
    "coding": 0.92,
    "rag": 0.55,
    "reasoning": 0.70,
    "edge": 0.10
  }
}
```

### 6.2 `benchmarks.json`

Best models per category and tier (`edge`, `workstation`, `enterprise`). The `id`s must exist in `models.json`.

### 6.3 Catalog MVP priority

| id | ollama_tag | main category |
|----|------------|---------------|
| qwen2.5-1.5b | qwen2.5:1.5b | edge |
| qwen2.5-7b | qwen2.5:7b | general |
| qwen2.5-coder-7b | qwen2.5-coder:7b | coding |
| qwen2.5-coder-32b | qwen2.5-coder:32b | coding |
| llama3.1-8b | llama3.1:8b | general |
| llama3.3-70b | llama3.3 | reasoning |
| codegemma-7b | codegemma:7b | coding |
| mistral-3-3b-instruct | mistral:3b | edge |

---

## 7. Intent classification

### 7.1 Categories

`coding`, `rag`, `reasoning`, `translation`, `vision`, `voice`, `edge`, `general`

### 7.2 MVP: keyword rules (no LLM)

Implement in `router/intent.py`.

### 7.3 Phase 2 (optional)

Keyword/intent/capability-router style patterns; implement in `ci2lab/router/` without external dependencies.

---

## 8. Selection algorithm

See sections 8.1–8.4 of the original plan (edge/workstation/enterprise tiers, VRAM/RAM filter, tier fallback, ordering by `benchmark_score`).

---

## 9. Ollama runtime (MVP)

- API: `http://localhost:11434`
- OpenAI-compatible: `http://localhost:11434/v1`
- Config: `~/.ci2lab/config.toml`

---

## 10. CLI

```bash
ci2lab doctor
ci2lab hardware [--json]
ci2lab models list [--category coding] [--fits]
ci2lab models show <id>
ci2lab models recommend "<prompt>" [--json]
ci2lab models pull <id|tag>
ci2lab prepare "<prompt>"
```

---

## 11. Global configuration

`~/.ci2lab/config.toml` — see the original plan.

---

## 12. Tests

Location: **`IAmultiagentica/tests/`**

Minimal cases: 6 GB VRAM, 24 GB VRAM, CPU 32 GB RAM, 4 GB VRAM + reasoning.

---

## 13. Reference material (outside the project)

Repos in `Ci2Lab/` (the **parent** folder of `IAmultiagentica/`):

| Path | Use |
|------|-----|
| `../claude-code-main/` | Prompts and tool descriptions |
| `../odysseus-dev/` | agent_loop, tool_parsing, schemas |
| `../opencode-dev/` | Tool registry, permissions |
| `../deepagents-main/` | BASE_AGENT_PROMPT, filesystem middleware |
| Project model table | Source for `catalog/models.json` |
| Project benchmarks | Source for `catalog/benchmarks.json` |

**Do not** copy these repos into `IAmultiagentica/`. **Do not** import them as packages.

---

## 14. Final integration with the harness

```python
from ci2lab.pipeline import prepare_session
from ci2lab.harness import run_agent

profile, selection = prepare_session(prompt)
run_agent(user_prompt=prompt, selection=selection, hardware=profile)
```

| Field | Use in the harness |
|-------|--------------------|
| `selection.ollama_tag` | Model in the API |
| `selection.backend_url` | OpenAI-compatible base URL |
| `selection.tool_mode` | `native` vs `fenced` |
| `selection.context_length` | History trimming |

---

## 15. Implementation order

1. `ci2lab/contracts/types.py` — **already exists**
2. `catalog/models.json` + `benchmarks.json`
3. `hardware/profiler.py`
4. `router/intent.py` + `router/selector.py` + `router/resolve.py`
5. `runtime/ollama.py` + `ensure_model_ready`
6. `pipeline.py` + CLI
7. Tests

**Milestone:** `ci2lab prepare "program really well" --json` from `IAmultiagentica/`.

---

## 16. Definition of done

- [ ] Always work from `IAmultiagentica/` (`pip install -e .`)
- [ ] `ci2lab hardware` works on Windows
- [ ] Catalog ≥10 models + `benchmarks.json`
- [ ] `resolve_model()` → stable `ModelSelection`
- [ ] `ensure_model_ready()` with Ollama
- [ ] Tests with mocks (no real GPU)
- [ ] `ci2lab prepare --json` consumable by the harness

---

## 17. FAQ

**Where do I clone / develop?** `cd Ci2Lab/IAmultiagentica`

**Python?** 3.11+

**pyproject.toml?** At the root of `IAmultiagentica/`

**Reference repos?** Siblings in `Ci2Lab/`, not inside the project

---

*Contract: `IAmultiagentica/ci2lab/contracts/types.py`.*
