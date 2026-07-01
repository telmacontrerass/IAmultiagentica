---
name: llm_enricher
title: LLM enricher with structured output, cache and anti-hallucination
description: Reusable layer to classify/enrich lists via an LLM with strict JSON-Schema output — normalises and caches by key, post-validates the response (dropping hallucinated names and out-of-range values), lazily imports the SDK, and degrades silently to a neutral result on any failure.
when_to_use: Classifying or enriching a list of items with an LLM where you need per-key caching, strict schema output, and anti-hallucination post-validation.
kind: integration
tags: llm, openai, structured-output, json-schema, cache, anti-hallucination, prompt-composition, graceful-degradation
requires: openai
yard_id: yard-fb832239e3
source_repo: Proyecto-Alvaro
signature: sha256:378a9926c2256d04e60c6c4ce59a3e774369a3a779e6b5b8f922299005597209
---

```json
{
  "entrypoints": [
    {
      "function": "_parsear_output",
      "module": "enriquecedor_llm",
      "ready": "pure",
      "summary": "Extract a JSON object from LLM text, stripping ```json fences. Raises ValueError if unparseable.",
      "parameters": {
        "type": "object",
        "properties": {"texto": {"type": "string"}},
        "required": ["texto"]
      }
    },
    {
      "function": "_normalizar",
      "module": "enriquecedor_llm",
      "ready": "pure",
      "summary": "Lower-case and strip accents from a name for cache-key comparison.",
      "parameters": {
        "type": "object",
        "properties": {"texto": {"type": "string"}},
        "required": ["texto"]
      }
    },
    {
      "function": "limpiar_cache",
      "module": "enriquecedor_llm",
      "ready": "pure",
      "summary": "Clear the module's in-process caches (useful for tests).",
      "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
      "function": "promover_tier4",
      "module": "enriquecedor_llm",
      "ready": "needs_config",
      "requires": ["openai"],
      "note": "The system prompt (_SYSTEM_PROMPT) and strict output schema (_SCHEMA_PROMOCIONES) were redacted from the salvaged source, so the live LLM call cannot run correctly. Supply your own prompt + JSON Schema to port it — see the porting guide.",
      "summary": "Promote 'tier 4' businesses via an LLM with structured output, cache and anti-hallucination.",
      "parameters": {
        "type": "object",
        "properties": {
          "negocios_t4": {"type": "array"},
          "openai_api_key": {"type": "string"},
          "modelo": {"type": "string"},
          "base_dir": {"type": "string"}
        },
        "required": ["negocios_t4", "openai_api_key"]
      }
    }
  ]
}
```

# LLM enricher

Directly reusable: the text normaliser (NFD + casefold), the output parser that
strips ```json fences, the per-normalised-key cache pattern, the anti-hallucination
post-validation (drop names never sent, drop out-of-range values, consolidate
duplicates), the lazy SDK import, and the silent degradation to a neutral result.

**Porting guide.** Project-specific and redacted: the system prompt and the
output JSON Schema (both elided for privacy), the concrete output categories,
and the input/output item shapes. To port `promover_tier4`: supply your own
strict schema and system prompt, adjust the item keys, and set the valid value
set. The pure helpers above run unchanged.
