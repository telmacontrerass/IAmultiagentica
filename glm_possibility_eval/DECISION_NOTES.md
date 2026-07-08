# GLM decision notes

## Short answer

GLM is worth exploring, but it should be treated as a private-server /
enterprise-local candidate, not as a default laptop-local model.

The strongest reason to evaluate it is conceptual fit: GLM-4.5 and later models
are explicitly positioned around agentic, reasoning, and coding tasks, and their
MoE design gives high active capability per token. That matches ci2lab's paper
argument: local/private agents can recover reliability through harness
mechanisms rather than fine-tuning.

The strongest reason not to implement it immediately as a default is hardware.
The official GLM-4.5 family is far beyond this workstation class. This machine
has 8 GB RAM and no NVIDIA VRAM; GLM-4.5-Air FP8 still targets multiple H100s
for full context. A smaller option such as GLM-4.7-Flash may be the practical
entry point if it is available in the target environment.

## Questions this eval answers

1. Can GLM run in the ci2lab harness through a private endpoint?
2. Does native tool calling work better than fenced tool calling for this model?
3. Does GLM improve agentic reliability on coding, search, and patch tasks?
4. Does GLM preserve the privacy claim by keeping all inference local/private?
5. Does GLM reduce failure classes that matter for the paper: parser failures,
   stalls, wrong edits, false positives, and excess token use?

## Evidence needed before implementation

Run this isolated suite with:

- current baseline model, e.g. `qwen2.5-coder:32b`;
- GLM candidate, ideally `GLM-4.7-Flash` or `GLM-4.5-Air-FP8`;
- same sample count, ideally `--samples 5`;
- same task list and same private inference endpoint.

Record:

- Pass@1 / Pass@k;
- median latency;
- tokens per solved task;
- false positive rate;
- failure classifications;
- tool violation count;
- model serving hardware.

## Go / no-go recommendation

Go if GLM beats or matches Qwen on pass rate and false positives while staying
within acceptable latency/cost on private hardware.

No-go for default local install if it requires multi-GPU server hardware that
the expected user does not have.

Middle-ground recommendation: add GLM as an optional documented backend profile
first. Only add catalog defaults after real runs show a practical deployable
variant.
