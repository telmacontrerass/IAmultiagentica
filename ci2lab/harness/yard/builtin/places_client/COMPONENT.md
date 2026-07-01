---
name: places_client
title: Google Places API client with grid search and adaptive subdivision
description: Google Places API (New) client — text search over a grid covering a bounding box, deduped by id and recursively subdividing cells that hit the result cap; plus nearby search, circular-bias text search, and robust mall detection from a postal address.
when_to_use: Enumerating places in a geographic rectangle via Google Places API, or detecting whether an address denotes a shopping mall.
kind: api-client
tags: google-places, geocoding, grid-search, api-client, dedup, address-normalization, mall-detection
requires: requests
yard_id: yard-7cd8ccaab2
source_repo: Proyecto-Alvaro
signature: sha256:dd86ce215ea186623beeb98d46059801044404c0336708488dcfbe07ee76d142
---

```json
{
  "entrypoints": [
    {
      "function": "es_centro_comercial",
      "module": "places_api",
      "ready": "pure",
      "summary": "Detect a shopping mall from a postal address by contiguous normalised-token subsequence (avoids the 'Centro' district false positive).",
      "parameters": {
        "type": "object",
        "properties": {
          "direccion": {
            "type": "string"
          }
        },
        "required": [
          "direccion"
        ]
      }
    },
    {
      "function": "buscar_opticas_places_api",
      "module": "places_api",
      "ready": "needs_key",
      "requires": [
        "requests"
      ],
      "secret_params": [
        "api_key"
      ],
      "summary": "Single Places API searchText call restricted to a lat/lon rectangle.",
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
          "api_key": {
            "type": "string"
          },
          "text_query": {
            "type": "string",
            "description": "Search text (default 'óptica')."
          }
        },
        "required": [
          "lat_min",
          "lon_min",
          "lat_max",
          "lon_max",
          "api_key"
        ]
      }
    },
    {
      "function": "buscar_opticas_en_grid",
      "module": "places_api",
      "ready": "needs_key",
      "requires": [
        "requests"
      ],
      "secret_params": [
        "api_key"
      ],
      "summary": "Grid search over a bounding box with recursive cell subdivision and dedup by id.",
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
          "api_key": {
            "type": "string"
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
          "lon_max",
          "api_key"
        ]
      }
    },
    {
      "function": "buscar_lugares_text_circular",
      "module": "places_api",
      "ready": "needs_key",
      "requires": [
        "requests"
      ],
      "secret_params": [
        "api_key"
      ],
      "summary": "Places searchText with circular locationBias (soft), returning up to top_k {place_id, nombre, latitud, longitud}.",
      "parameters": {
        "type": "object",
        "properties": {
          "lat": {
            "type": "number"
          },
          "lon": {
            "type": "number"
          },
          "query": {
            "type": "string"
          },
          "api_key": {
            "type": "string"
          },
          "radio_metros": {
            "type": "number",
            "description": "Bias radius (default 1500)."
          },
          "top_k": {
            "type": "integer",
            "description": "Max results (default 2)."
          }
        },
        "required": [
          "lat",
          "lon",
          "query",
          "api_key"
        ]
      }
    }
  ]
}
```

# Google Places client

Directly reusable: the HTTP client to Places API (searchText/searchNearby), the
grid search with recursive subdivision of saturated cells and dedup by id, the
mall detection by contiguous normalised-token subsequence, and the
circular-bias text search. `buscar_opticas_en_grid` imports the sibling
`geo_toolkit` module (`geometria`) for the grid computation — the Yard runner
puts every component's `core/` folder on `sys.path` so that cross-import
resolves.

**Porting guide.** To reuse elsewhere: (1) supply your own grid/geometry module
or keep `geo_toolkit`; (2) parameterise the default `text_query` and the
`includedPrimaryTypes` of the nearby search (currently retail types).
