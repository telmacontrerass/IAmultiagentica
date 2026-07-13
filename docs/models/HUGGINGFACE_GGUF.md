# Hugging Face GGUF Imports

CI2Lab supports a pragmatic local workflow for GGUF files that you have already
downloaded from Hugging Face. It does not download full repositories, does not
embed Transformers, and does not add a new serving platform. Ollama remains the
serving layer for this first version.

## Concepts

Separate three things:

- Physical model: the concrete GGUF file on disk.
- Execution profile: template, stops, context, parameters and tool mode.
- Stable alias: the clean CI2Lab/Ollama name the user types.

Example physical model:

```text
models/glm/GLM-4-9B-0414-Q4_K_M.gguf
```

Example stable alias:

```text
glm-4-9b-q4
```

Avoid encoding every experiment into the Ollama model name:

```text
glm-4-9b-local:q4_k_m_tpl_16k
```

If a variant is meaningful, prefer a profile-style name such as
`glm-4-9b-q4@8k` or `glm-4-9b-q4@16k`. For one-off experiments, use
`--context-length` or `--tool-mode` as explicit overrides.

## Where Metadata Lives

Bundled models remain in:

```text
ci2lab/catalog/models.json
```

Imported local models are stored separately:

```text
~/.ci2lab/models/imported_models.json
```

Tests and advanced users can override that path with:

```text
CI2LAB_IMPORTED_MODELS_PATH
```

Templates live in:

```text
ci2lab/catalog/model_templates.json
```

The first bundled template is `glm4-chat`. The structure is ready for more
families such as `qwen2.5`, `llama3`, `mistral`, `deepseek`, `gemma`, and
`glm4`.

## Import A GGUF

First ensure the GGUF file exists locally. Then inspect the generated Modelfile:

```powershell
ci2lab models import-gguf `
  --repo unsloth/GLM-4-9B-0414-GGUF `
  --file GLM-4-9B-0414-Q4_K_M.gguf `
  --path models/glm/GLM-4-9B-0414-Q4_K_M.gguf `
  --id glm-4-9b-q4 `
  --family glm4 `
  --template glm4-chat `
  --ctx 16384 `
  --tool-mode fenced `
  --dry-run
```

Create the Ollama model and save the CI2Lab metadata:

```powershell
ci2lab models import-gguf `
  --repo unsloth/GLM-4-9B-0414-GGUF `
  --file GLM-4-9B-0414-Q4_K_M.gguf `
  --path models/glm/GLM-4-9B-0414-Q4_K_M.gguf `
  --id glm-4-9b-q4 `
  --family glm4 `
  --template glm4-chat `
  --ctx 16384 `
  --tool-mode fenced
```

The command:

1. Verifies the local GGUF file exists.
2. Loads the named template.
3. Generates an Ollama Modelfile.
4. Runs `ollama create <id> -f <Modelfile>`.
5. Saves metadata in the imported-model registry.

## Download One File Only

If you use Hugging Face tooling, download the single GGUF file rather than the
whole repository:

```powershell
python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='unsloth/GLM-4-9B-0414-GGUF', filename='GLM-4-9B-0414-Q4_K_M.gguf', local_dir='models/glm')"
```

This is intentionally outside CI2Lab's import command in the first version. The
importer expects a concrete local file.

## Context Resolution

Imported profiles carry their own context length. CI2Lab uses the same value for
internal budgeting/compaction, and the generated Ollama Modelfile sets
`PARAMETER num_ctx`.

Priority:

```text
CLI explicit --context-length
> CI2LAB_NUM_CTX
> imported model profile
> bundled catalog model profile
> ModelSelection default
```

## Running The Imported Model

Check Ollama first:

```powershell
ollama run glm-4-9b-q4
```

Then run CI2Lab:

```powershell
ci2lab agent "Crea un archivo glm_smoke.txt con exactamente este contenido: GLM_OK. Despues lee el archivo y confirma si es correcto." --model glm-4-9b-q4 --no-stream --yes
```

Override only when experimenting:

```powershell
ci2lab agent "..." --model glm-4-9b-q4 --context-length 8192
ci2lab agent "..." --model glm-4-9b-q4 --tool-mode native
```

## Why Templates Matter

`FROM model.gguf` only tells Ollama which weights to load. It does not guarantee
that the model sees the chat format it was trained for. Some families need
family-specific role markers, prefix tokens, and stops. GLM-4 chat GGUFs need
`[gMASK]<sop>` plus `<|system|>`, `<|user|>`, and `<|assistant|>` roles.

That knowledge belongs in the template catalog, not in the agent loop.

## Current Limitations

- No automatic Hugging Face download inside `import-gguf`.
- No automatic template detection from GGUF metadata yet.
- No profile editing command yet; re-run import with the same id to upsert.
- Only `temperature` is carried into `ModelSelection`; other parameters are used
  in the generated Ollama Modelfile.
- Imported profiles are local to the machine/user unless you set
  `CI2LAB_IMPORTED_MODELS_PATH` to a project path.
