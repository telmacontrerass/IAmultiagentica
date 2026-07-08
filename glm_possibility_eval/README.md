# GLM possibility evaluation

This folder is intentionally separate from `benchmarks/`.

Goal: decide whether adding a GLM-family open model is worth implementing in
ci2lab as a local/private agent model option. The evaluation focuses on the
questions that matter for this project:

- Does GLM work with the ci2lab harness without fine-tuning?
- Does it follow fenced/native tool protocols reliably enough?
- Does it preserve the local/privacy story?
- Does it improve coding and agentic reliability enough to justify integration?
- Is the hardware cost compatible with realistic local deployment?

## Current recommendation gate

Do not add GLM to the default model catalog until at least one GLM variant can
be run locally or on a private OpenAI-compatible endpoint and passes this
isolated eval.

Recommended implementation status:

- `research/prototype`: yes.
- `default local model`: no, unless a small GLM variant is available on the
  target hardware.
- `enterprise/private server model`: likely yes, if served through vLLM or
  SGLang with OpenAI-compatible chat completions.

## Official facts to verify before running

As of the public GLM-4.5/4.6/4.7 documentation:

- GLM-4.5 is a Mixture-of-Experts model for agentic, reasoning, and coding
  tasks.
- GLM-4.5 has 355B total parameters and 32B active parameters.
- GLM-4.5-Air has 106B total parameters and 12B active parameters.
- GLM-4.5/4.6/4.7 support tool calling through vLLM/SGLang.
- The full models are not laptop-class models. The official requirements list
  multiple H100 GPUs for full-featured inference, except the smaller
  GLM-4.7-Flash option.

Useful sources:

- https://github.com/zai-org/GLM-4.5
- https://arxiv.org/abs/2508.06471
- https://huggingface.co/zai-org/GLM-4.5
- https://huggingface.co/zai-org/GLM-4.5-Air

## Run commands

### 1. Fenced mode through Ollama or any compatible local tag

Use this only if the model is available through Ollama or if you are testing a
baseline model such as Qwen.

```bash
python glm_possibility_eval/run_glm_eval.py \
  --model qwen2.5-coder:32b \
  --backend ollama \
  --samples 1
```

### 2. GLM through a private OpenAI-compatible endpoint

Start vLLM or SGLang separately. Then run:

```bash
python glm_possibility_eval/run_glm_eval.py \
  --model glm-4.7-fp8 \
  --backend openai \
  --backend-url http://localhost:8000/v1 \
  --tool-mode native \
  --samples 3
```

For GLM-4.7 with vLLM, the upstream example uses options like:

```bash
vllm serve zai-org/GLM-4.7-FP8 \
  --tensor-parallel-size 4 \
  --tool-call-parser glm47 \
  --reasoning-parser glm45 \
  --enable-auto-tool-choice \
  --served-model-name glm-4.7-fp8
```

Adjust GPU count and model name to the available hardware.

## Decision thresholds

GLM is worth implementing as a first-class option if:

- It runs on a private/local endpoint without sending prompts to a third-party
  cloud API.
- It reaches at least the current Qwen baseline on pass rate for these tasks.
- It has no materially higher false-positive rate than Qwen.
- It does not increase median latency or tokens-per-solved-task beyond what the
  project can accept for the target deployment.
- The integration path is simple: OpenAI-compatible backend, native tool mode,
  and no GLM-specific changes to the core harness beyond catalog metadata and
  documentation.

If it only works on multi-H100 infrastructure, it may still be worth supporting
as an enterprise/private-server profile, but not as a default "local laptop"
model.
