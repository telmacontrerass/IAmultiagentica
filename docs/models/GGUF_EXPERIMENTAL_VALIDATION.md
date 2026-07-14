# Experimental GGUF inspection and llama.cpp validation

This iteration borrows Odysseus's separation between acquisition, inspection,
serving, and validation. Odysseus is not a dependency: CI2Lab only needs a small,
auditable lifecycle around tools already installed by the operator.

Importing identifies and hashes an artifact. Serving starts a temporary runtime.
Template adaptation changes the contract between runtime variables and Jinja.
These are deliberately separate operations. The stable Ollama profile, aliases,
and registry are never modified by the experimental commands.

## GLM-4

Inspect the local file:

```powershell
ci2lab models inspect-gguf `
  --model-path models\glm4-9b-chat\glm-4-9b-chat-Q4_K_M.gguf `
  --output-dir runs\imports
```

Validate using an already-installed llama.cpp server:

```powershell
ci2lab models validate-gguf `
  --model-path models\glm4-9b-chat\glm-4-9b-chat-Q4_K_M.gguf `
  --runtime llama.cpp `
  --llama-server-path C:\path\to\llama-server.exe `
  --context-length 16000 `
  --no-stream
```

`CI2LAB_LLAMA_SERVER` may replace the CLI binary option. Resolution order is CLI,
environment, configured value (API), then `PATH`. CI2Lab does not install or
download llama.cpp.

Each validation writes metadata, the original template, template analysis,
runtime argv and logs, requests, raw responses, deterministic gates, and a short
report beneath `runs/imports`. A tools pass requires a valid call to the fixed
`add` function, real local execution, reinjection of its result, and a final
answer without a repeated call. Merely emitting JSON does not pass.

The current implementation exposes `TemplateAdapter` and
`RuntimeTemplateContract`, but does not adapt GLM's legacy Jinja. In particular,
inspection can show that a GGUF template reads `messages[*].tools` while
llama.cpp supplies global `tools`. A future adapter may create a candidate for
that mismatch, but deterministic validation must still approve it before any
production registration is considered.

Real-server tests are opt-in and require both an existing GGUF and
`llama-server`; ordinary CI never downloads either.
