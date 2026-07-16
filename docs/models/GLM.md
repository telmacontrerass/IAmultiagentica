# GLM local model

CI2Lab uses one canonical local GLM installation:

- CI2Lab alias: `glm4`
- Ollama tag: `ci2lab/glm-4-9b-chat:q4_k_m`
- Source: `bartowski/glm-4-9b-chat-GGUF`
- GGUF: `models/glm4-9b-chat/glm-4-9b-chat-Q4_K_M.gguf`
- Quantization: Q4_K_M
- Native metadata context: 131,072 tokens
- Operational context: 16,384 tokens
- Template: `glm4-chat`
- Recommended tool mode: `fenced`

The model was selected by a controlled local comparison against Unsloth
GLM-4-9B-0414 Q4_K_M. Both passed ordinary chat, system-prompt and multiround
checks. Bartowski was retained because the real CI2Lab tool test completed with
one traced tool call and correct result reinjection in two rounds; the Unsloth
candidate repeated the call and exhausted its three-round limit.

## Run it

```powershell
ci2lab --backend ollama --model glm4 agent "Responde únicamente con la palabra OK."
```

For a traced tool run:

```powershell
ci2lab --backend ollama --model glm4 --tool-mode fenced --no-stream agent "Usa read_file para leer README.md y resume la primera línea."
```

`native` can still be requested for diagnostics, and textual JSON calls remain
traceable through `source_protocol` and `parser_id`. This GLM/Ollama combination
did not produce structured `message.tool_calls` reliably, so fenced is the
verified default.

## Import on another machine

```powershell
hf download bartowski/glm-4-9b-chat-GGUF `
  glm-4-9b-chat-Q4_K_M.gguf `
  --local-dir models/glm4-9b-chat

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

Do not create separate Ollama tags for tool mode or context length. Override
those at execution time when testing; keep the physical model canonical.

## Verify

```powershell
ollama show ci2lab/glm-4-9b-chat:q4_k_m
ci2lab models list
ollama list
```

The expected steady state is one GLM tag, one imported profile, and one GLM
GGUF. The pre-cleanup inventory and decision evidence are recorded in
`audit/glm_cleanup_inventory_20260714.md`.
