# GLM Models In CI2Lab

CI2Lab does not hardcode GLM behavior in the agent loop. GLM-specific prompt
formatting lives in the model template catalog, and local GGUF imports live in a
machine-local model registry.

## Validated GGUF Case

Validated manually:

- Hugging Face repo: `unsloth/GLM-4-9B-0414-GGUF`
- GGUF file: `GLM-4-9B-0414-Q4_K_M.gguf`
- Local path: `models/glm/GLM-4-9B-0414-Q4_K_M.gguf`
- CI2Lab/Ollama alias: `glm-4-9b-q4`
- Template: `glm4-chat`
- Context: `16384`
- Tool mode: `fenced`

The minimal Ollama Modelfile:

```text
TEMPLATE {{ .Prompt }}
```

is not enough for this GLM model. It tends to produce malformed output,
repetitions, or code-like text because the chat roles are missing. The working
template starts with `[gMASK]<sop>` and emits GLM role markers:

```text
[gMASK]<sop>{{ if .System }}<|system|>
{{ .System }}{{ end }}<|user|>
{{ .Prompt }}<|assistant|>
{{ .Response }}
```

The bundled `glm4-chat` template also adds these stops:

```text
<|user|>
<|assistant|>
<|system|>
<|observation|>
<|endoftext|>
<eop>
```

## Import Command

Use one stable alias instead of creating names such as `_tpl` or `_16k`:

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

Dry-run first if you want to inspect the generated Modelfile:

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

After import, CI2Lab resolves the profile automatically:

```powershell
ci2lab agent "Crea un archivo glm_smoke.txt con exactamente este contenido: GLM_OK. Despues lee el archivo y confirma si es correcto." --model glm-4-9b-q4 --no-stream --yes
```

The profile supplies:

- `ollama_tag = glm-4-9b-q4`
- `context_length = 16384`
- `tool_mode = fenced`
- `temperature = 0.1`
- `top_p = 0.8` in the Ollama Modelfile

## Context

Ollama and CI2Lab must agree about context. The import command writes:

```text
PARAMETER num_ctx 16384
```

and the imported CI2Lab profile stores:

```json
{"context_length": 16384}
```

Resolution priority is:

```text
--context-length > CI2LAB_NUM_CTX > imported profile > bundled catalog > default
```

Use `--context-length` only for experiments. If a context value is part of the
intended model profile, prefer importing or updating the profile.

## Tool Mode

For this GLM GGUF, `fenced` is the recommended default. It avoids relying on
native function calling support from the model/server. You can still override it:

```powershell
ci2lab agent "..." --model glm-4-9b-q4 --tool-mode native
```

## Direct Ollama Check

Check that Ollama can load the imported alias:

```powershell
ollama run glm-4-9b-q4
```

Then ask a short role-sensitive prompt and verify it answers normally before
running CI2Lab tool tasks.

## External Server Route

For large GLM variants, an OpenAI-compatible server such as vLLM or SGLang may
be a better serving layer. CI2Lab does not depend on either. Point CI2Lab at the
server and usually start with fenced tools:

```powershell
ci2lab --backend openai --base-url http://localhost:8000/v1 --model glm-local --tool-mode fenced agent "Crea prueba.txt con hola"
```

In that route, configure long context in the serving runtime. CI2Lab still uses
its `context_length` for budgeting and compaction.
