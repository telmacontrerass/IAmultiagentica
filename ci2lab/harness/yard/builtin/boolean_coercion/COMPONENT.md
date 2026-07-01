---
name: boolean_coercion
title: Boolean cell coercion with text normalisation
description: Coerce spreadsheet-style cell values to a tri-state boolean, tolerating None/bool/int/float/str and locale variants ("sí"/"no"/"true"/"false"/1/0), with diacritic-insensitive text normalisation.
when_to_use: Importing spreadsheet/CSV data where a yes/no column may be accented, mixed-type, or ambiguous and you need an explicit None for "not interpretable".
kind: utility
tags: boolean-coercion, text-normalization, diacritics, casefold, spreadsheet-import, type-coercion
requires:
yard_id: yard-8d14121485
source_repo: Proyecto-Alvaro
signature: sha256:e531f9cebd85c410cb1ef7cc5d78a38a0551e480cbb5d4ea53cf7720aca3c903
---

```json
{
  "entrypoints": [
    {
      "function": "_a_bool",
      "module": "config_listas",
      "ready": "pure",
      "summary": "Interpret a cell as boolean; returns True/False, or None when the value is not interpretable (tri-state).",
      "parameters": {
        "type": "object",
        "properties": {
          "valor": {"description": "The cell value: None, bool, int/float, or str (e.g. 'Sí', 'no', 'true', '1')."}
        },
        "required": ["valor"]
      }
    },
    {
      "function": "_normalizar",
      "module": "config_listas",
      "ready": "pure",
      "summary": "Strip diacritics and casefold a string so 'Sí' compares equal to 'si'.",
      "parameters": {
        "type": "object",
        "properties": {
          "texto": {"description": "Text to normalise (any type is coerced to str; None → '')."}
        },
        "required": ["texto"]
      }
    }
  ]
}
```

# Boolean cell coercion

Two small helpers salvaged from a spreadsheet-import module. `_a_bool` is the
value: it recognises `None`, native `bool`, numeric `0`/`1`, and the string
tokens `si`/`true` (→ `True`) and `no`/`false` (→ `False`), returning `None` for
anything else so the caller can decide how to treat an unknown cell. `_normalizar`
(diacritics stripped via `unicodedata` NFKD + casefold) backs the string
matching.

**Porting guide.** Reusable as-is; only depends on the standard library. To
adapt: the affirmative/negative literals (`si`/`true`, `no`/`false`) are
hard-coded — parameterise them for other languages or domain tokens, and expose
the helpers without the leading underscore if you want them as public API.
