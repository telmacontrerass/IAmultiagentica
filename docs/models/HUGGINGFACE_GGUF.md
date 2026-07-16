# Importing Hugging Face GGUF models

`ci2lab models import-gguf` creates one Ollama tag from an already downloaded
GGUF and stores a machine-local CI2Lab profile. The profile keeps the short
human alias separate from the physical Ollama tag, so context and tool mode do
not need extra aliases.

## Capability and transaction policy

Importing a model does not verify tool calling. CI2Lab records inference,
tool-calling and security capabilities independently. A Jinja template is only
metadata: native tools are verified only after the backend returns a valid
structured `tool_calls` response. A family adapter is verified only after its
empirical smoke suite completes. Fenced mode is an experimental configured
fallback and is never promoted merely because parsing is possible.

Protocol selection has one precedence order:

1. valid backend-native `tool_calls` -> `native` / `openai_tool_calls`;
2. empirically verified family adapter -> `adapted_native` / adapter parser;
3. explicitly enabled fallback -> unverified `fenced`;
4. otherwise tools are unavailable or unverified.

The registry is updated atomically only after GGUF inspection, hashing,
`ollama create`, structured `ollama show --json`, and minimal inference that
returns `OK`. A failure before creation is `IMPORT_FAILED`. A failure after an
external model was created is `IMPORT_PARTIALLY_COMPLETED`; the previous valid
registry is not overwritten. Inference-only promotion is distinct from
`IMPORTED_TOOLS_VERIFIED`.

The short suite is `gguf-import-smoke`. It reports inference, tool calling,
multiround continuation, verified writing, complex schemas, workspace
confinement and untrusted-content resistance independently. Prompt-injection
failure does not falsify technical tool calling: the executor remains the
security boundary.

Run it after import without recreating the model:

```powershell
ci2lab models gguf-import-smoke `
  --model qwen3-4b `
  --backend ollama `
  --request-timeout 180
```

Use `--no-promote` for evidence-only execution. For a managed llama.cpp run,
add `--backend llama-cpp --model-path <model.gguf> --llama-server-path
<llama-server>`. The runner reuses one server, starts a fresh conversation and
workspace per case, writes structured evidence under `runs/imports`, and always
stops a server it started. `import-gguf --run-smoke --smoke-protocol native`
runs the same implementation during import.

Capability promotion is atomic and monotonic: a failed rerun does not remove a
previous verification. The stored evidence records suite/version, timestamp,
backend and artifact path. Indirect prompt-injection resistance remains a
separate security result.

## Ollama identity and idempotency

CI2Lab captures `ollama show <tag> --json` before and after creation. The local
identity combines GGUF SHA-256, repository, filename, architecture,
quantization, embedded-template hash, rendered Ollama-template hash, Modelfile
hash, context, parameters, stops and configured protocol/adapter.

- `ALREADY_IMPORTED_EQUIVALENT`: the traced identity matches; no recreation.
- `IMPORT_CONFLICT`: the tag is tracked but hash/template/parameters differ.
- `PROFILE_MODEL_INCONSISTENT`: a profile exists but its Ollama model is absent;
  an explicit import can repair it without deleting the profile first.
- `EXTERNAL_MODEL_UNTRACKED`: Ollama has the tag but CI2Lab lacks sufficient
  provenance; it is not silently adopted.
- `IMPORT_PARTIALLY_COMPLETED`: an external effect could not be safely reverted.

`model` and `model:latest` are equivalent, while `model:q4` and `model:q8` are
distinct. Rollback is attempted only when the tag was absent beforehand, the
created snapshot has a digest, and a fresh snapshot still has that exact
digest. A pre-existing or concurrently replaced model is never removed.

## Troubleshooting

- Use `hf`, not the retired `huggingface-cli`, and check disk space first.
- Lower context when RAM/VRAM is insufficient or startup times out.
- A present but unrecognized template does not imply native tools.
- `model` and `model:latest` are equivalent; `model:q4` and `model:q8` are not.
- If `ollama show --json` is empty or inconsistent, the registry is not updated.
- After interruption, remove only a model known to have been created by that
  attempt. Never delete a pre-existing alias automatically.
- Check for residual `llama-server` processes after live validation.

| Family | Inference | Tool calling | Path |
|---|---:|---:|---|
| GLM-4 Chat | Yes | Yes | Specific adapter |
| Qwen3 | Yes | Yes | Direct native |
| Unknown | Depends | Not assumed | Detect and verify |

## Canonical GLM example

```powershell
ci2lab models import-gguf `
  --repo bartowski/glm-4-9b-chat-GGUF `
  --file glm-4-9b-chat-Q4_K_M.gguf `
  --path models/glm4-9b-chat/glm-4-9b-chat-Q4_K_M.gguf `
  --id glm4 `
  --ollama-tag ci2lab/glm-4-9b-chat:q4_k_m `
  --family glm4 `
  --template glm4-chat `
  --ctx 16384 `
  --tool-mode fenced
```

Preview the generated Modelfile without creating a tag or profile by adding
`--dry-run`.

The bundled GLM Go template serializes system messages, multiround history,
dynamic `.Tools`, assistant tool calls and tool results as
`<|observation|>`. It iterates only over schemas supplied by CI2Lab, so obsolete
or model-embedded historical tools are never hard-coded into the active prompt.

## Naming and execution

- `--id` is the concise CI2Lab alias, for example `glm4`.
- `--ollama-tag` is the one physical tag, for example
  `ci2lab/glm-4-9b-chat:q4_k_m`.
- `--ctx` is the default operating context stored in the profile.
- `--tool-mode` is a profile/execution setting, not part of the model name.

```powershell
ci2lab models list
ci2lab --backend ollama --model glm4 agent "Responde únicamente OK."
```

For GLM, fenced tools are recommended because they were validated end to end.
Native mode sends API schemas without duplicating the full textual tool manual,
but the tested model used observable text/JSON fallback rather than structured
Ollama `message.tool_calls`.

See `docs/models/GLM.md` for the validated configuration and
`audit/glm_cleanup_inventory_20260714.md` for the retained-versus-discarded
comparison.
