---
name: facade_estimator
title: Facade-attribute estimator with Street View + vision LLM
description: Download a Street View image for an address and classify a facade attribute with a multimodal LLM — metadata precheck, timed download, base64 encoding, and fenced-JSON response parsing.
when_to_use: Estimating a visual attribute of a storefront/facade from its address via Street View plus a vision LLM.
kind: integration
tags: google-street-view, openai, vision-llm, image-classification, multimodal, base64-image, json-extraction
requires: requests openai
yard_id: yard-8a4cadeb43
source_repo: Proyecto-Alvaro
signature: sha256:8ba990c34efe9d89da4b2a8b2bdacb1fb33527017b2cdc566408a1cbd4d013db
core_sha256: sha256:cda0f8f48842e43fc92df7b94ddc8857f1dbc207b1f41d42834cb8543ad99924
---

```json
{
  "entrypoints": [
    {
      "function": "_parsear_respuesta_llm",
      "module": "estimacion_fachada",
      "ready": "pure",
      "summary": "Extract a JSON object from LLM text, stripping ```json fences.",
      "parameters": {
        "type": "object",
        "properties": {
          "texto": {
            "type": "string"
          }
        },
        "required": [
          "texto"
        ]
      }
    },
    {
      "function": "_encode_image",
      "module": "estimacion_fachada",
      "ready": "pure",
      "path_params": ["ruta"],
      "summary": "Read a local image file and return its base64 string.",
      "parameters": {
        "type": "object",
        "properties": {
          "ruta": {
            "type": "string",
            "description": "Path to a local image file."
          }
        },
        "required": [
          "ruta"
        ]
      }
    },
    {
      "function": "descargar_imagen_streetview",
      "module": "estimacion_fachada",
      "ready": "needs_key",
      "requires": [
        "requests"
      ],
      "secret_params": [
        "api_key"
      ],
      "path_params": [
        "ruta_destino"
      ],
      "summary": "Precheck Street View metadata and download the image for an address; returns True on success.",
      "parameters": {
        "type": "object",
        "properties": {
          "direccion": {
            "type": "string"
          },
          "ruta_destino": {
            "type": "string"
          },
          "api_key": {
            "type": "string"
          },
          "fov": {
            "type": "integer",
            "description": "Field of view (default 80)."
          }
        },
        "required": [
          "direccion",
          "ruta_destino",
          "api_key"
        ]
      }
    },
    {
      "function": "estimar_fachada",
      "module": "estimacion_fachada",
      "ready": "needs_config",
      "requires": [
        "requests",
        "openai"
      ],
      "note": "The vision prompt and the valid-category set (CATEGORIAS_VALIDAS) plus the output key mapping were redacted from the salvaged source, so the classification returns an empty result. Supply your own prompt/categories to port it — see the porting guide.",
      "summary": "Download the Street View image and estimate a facade attribute with a vision LLM.",
      "parameters": {
        "type": "object",
        "properties": {
          "candidata": {
            "type": "object",
            "description": "{id, direccion, nombre}"
          },
          "dir_imagenes": {
            "type": "string"
          },
          "places_api_key": {
            "type": "string"
          },
          "openai_api_key": {
            "type": "string"
          }
        },
        "required": [
          "candidata",
          "dir_imagenes",
          "places_api_key",
          "openai_api_key"
        ]
      }
    }
  ]
}
```

# Facade estimator

The reusable core is the pairing of street-image download + vision-LLM
classification. Directly reusable without changes: `descargar_imagen_streetview`
(metadata precheck + timed download), `_encode_image` and
`_parsear_respuesta_llm`.

**Porting guide.** To reuse: (1) replace the redacted prompt with your own and
adjust the response keys; (2) redefine the valid-category set (redacted
constant) and the output mapping; (3) adapt the `candidata` dict shape
(id/direccion/nombre) to your data model; (4) parameterise the filename pattern
and ensure `dir_imagenes` exists.
