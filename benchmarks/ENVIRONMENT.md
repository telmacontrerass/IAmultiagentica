# Benchmark environment

Record the exact environment for every benchmark run so results are
reproducible. Fill the `TODO` fields during the Day-5 model bring-up
(see [`docs/BENCHMARKING.md`](../docs/BENCHMARKING.md) §6).

## Hardware

| Field | Value |
| --- | --- |
| Machine | HP Z6 G5 A Workstation |
| CPU | AMD Threadripper PRO 7975WX (32c / 64t) |
| RAM | 128 GB |
| GPU | NVIDIA RTX A6000 (48 GB VRAM) |
| OS | Linux |
| ci2lab inference budget | ~44.6 GB VRAM (`hardware_tier: enterprise`) |

## Software / versions (pin these)

| Component | Value |
| --- | --- |
| ci2lab commit | `TODO: git rev-parse HEAD` |
| Ollama version | `TODO: ollama --version` |
| Shared model M | `qwen2.5-coder:32b` |
| M Ollama digest | `TODO: ollama show --modelfile qwen2.5-coder:32b` (record the digest) |
| M quantization | `TODO` (default Q4_K_M, or Q5/Q6) |
| `claude` CLI version (H1) | `TODO: claude --version` |
| Claude plan tier (H1) | `TODO` (Pro / Max) |
| `codex` CLI version | `TODO: codex --version` |
| ChatGPT plan tier (H1) | `TODO` (Plus / Pro / Team) |

## Protocol knobs (see §5.5)

| Knob | Value |
| --- | --- |
| temperature | 0 |
| k samples | 5 |
| context window (`num_ctx`) | `TODO` |
| per-run wall-clock cap | per task (`timeout_seconds`) |
| warm-up | 1 discarded run per (agent, model) |
