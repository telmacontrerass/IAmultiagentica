---
name: geo_toolkit
title: Geospatial toolkit — haversine, grid, distance matrix
description: Great-circle distance (haversine), a square-cell grid and perimeter rectangles over a bounding box, plus a Google Distance Matrix walking-distance client (single and batch).
when_to_use: Any geo task needing distance between lat/lon points, tiling a rectangle into search cells, or walking distances via Google Distance Matrix.
kind: utility
tags: geospatial, haversine, distance, grid-search, bounding-box, geometry, google-distance-matrix
requires: requests
yard_id: yard-173c5687f9
source_repo: Proyecto-Alvaro
signature: sha256:3c340c14c7f11268907d3e6a63397d56bb9c628484435eb1f69992bc1fe9a1f6
core_sha256: sha256:cb1524017a094d605102fe8f54a9614f9b148286c967c1b5fba7e2a424fdd181
---

```json
{
  "entrypoints": [
    {
      "function": "calcular_distancia_haversine",
      "module": "geometria",
      "ready": "pure",
      "summary": "Great-circle distance in metres between two lat/lon points.",
      "parameters": {
        "type": "object",
        "properties": {
          "lat1": {
            "type": "number"
          },
          "lon1": {
            "type": "number"
          },
          "lat2": {
            "type": "number"
          },
          "lon2": {
            "type": "number"
          }
        },
        "required": [
          "lat1",
          "lon1",
          "lat2",
          "lon2"
        ]
      }
    },
    {
      "function": "calcular_celdas_grid",
      "module": "geometria",
      "ready": "pure",
      "summary": "Tile a bounding box into ~square cells of side `lado_metros`; edge remainders fold into the last row/column.",
      "parameters": {
        "type": "object",
        "properties": {
          "lat_min": {
            "type": "number"
          },
          "lon_min": {
            "type": "number"
          },
          "lat_max": {
            "type": "number"
          },
          "lon_max": {
            "type": "number"
          },
          "lado_metros": {
            "type": "number",
            "description": "Cell side in metres (default 1000)."
          }
        },
        "required": [
          "lat_min",
          "lon_min",
          "lat_max",
          "lon_max"
        ]
      }
    },
    {
      "function": "calcular_rectangulos_perimetrales",
      "module": "geometria",
      "ready": "pure",
      "summary": "Four non-overlapping perimeter rectangles around a bounding box with a metre margin.",
      "parameters": {
        "type": "object",
        "properties": {
          "lat_min": {
            "type": "number"
          },
          "lon_min": {
            "type": "number"
          },
          "lat_max": {
            "type": "number"
          },
          "lon_max": {
            "type": "number"
          },
          "margen_metros": {
            "type": "number",
            "description": "Band width in metres (default 700)."
          }
        },
        "required": [
          "lat_min",
          "lon_min",
          "lat_max",
          "lon_max"
        ]
      }
    },
    {
      "function": "calcular_distancia_andando",
      "module": "geometria",
      "ready": "needs_key",
      "requires": [
        "requests"
      ],
      "secret_params": [
        "api_key"
      ],
      "summary": "Walking distance in metres between two 'lat,lon' points via Google Distance Matrix.",
      "parameters": {
        "type": "object",
        "properties": {
          "origen": {
            "type": "string",
            "description": "'lat,lon'"
          },
          "destino": {
            "type": "string",
            "description": "'lat,lon'"
          },
          "api_key": {
            "type": "string",
            "description": "Google Maps API key."
          }
        },
        "required": [
          "origen",
          "destino",
          "api_key"
        ]
      }
    },
    {
      "function": "calcular_distancias_andando_batch",
      "module": "geometria",
      "ready": "needs_key",
      "requires": [
        "requests"
      ],
      "secret_params": [
        "api_key"
      ],
      "summary": "Walking distances from one origin to many '|'-separated destinations in a single request.",
      "parameters": {
        "type": "object",
        "properties": {
          "origen": {
            "type": "string",
            "description": "'lat,lon'"
          },
          "destinos": {
            "type": "string",
            "description": "'lat1,lon1|lat2,lon2|...'"
          },
          "api_key": {
            "type": "string",
            "description": "Google Maps API key."
          }
        },
        "required": [
          "origen",
          "destinos",
          "api_key"
        ]
      }
    }
  ]
}
```

# Geospatial toolkit

The three pure functions (`calcular_distancia_haversine`,
`calcular_rectangulos_perimetrales`, `calcular_celdas_grid`) are reusable
directly. The Distance Matrix client (`calcular_distancia_andando` and its batch
variant) needs a Google Maps `api_key` and network access.

**Porting guide.** To harden quality: replace the broad `except Exception` +
`print` with typed exceptions and logging, add `timeout` to `requests.get`, add
retries/backoff and input validation, and test by patching `requests` (no API
cost). The `margen_metros`/`lado_metros` parameters and the `111000.0`
metres-per-degree constant are tunable.
