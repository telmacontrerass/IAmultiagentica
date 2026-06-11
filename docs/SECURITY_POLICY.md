# Politica de seguridad del arnés Ci2Lab

## Workspace

- Todas las herramientas de archivos y `bash` validan rutas respecto al `--workspace`.
- Rutas absolutas externas, `..` y comandos shell que referencian archivos fuera del workspace se bloquean **antes** de leer o ejecutar.
- `--yes` / `auto_confirm` **no salta** el confinamiento al workspace ni la blocklist de `bash`.
- `--yes` solo omite confirmaciones interactivas de `bash` (y de write/edit si `require_diff_preview=false`).

## Archivos sensibles dentro del workspace

`read_file` y `grep` bloquean u omiten archivos que parecen contener secretos:

- `.env`, `.env.*`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`
- `id_rsa`, `id_ed25519`
- rutas o nombres con `secret`, `credentials` o `token`

`read_file` e `inspect_file` devuelven `POLICY_SECRET_FILE_BLOCKED` sin leer contenido.

`write_file` y `edit_file` devuelven el mismo bloqueo al escribir en rutas sensibles (preview incluida).

`grep` omite archivos sensibles en busquedas recursivas y anota cuantos se saltaron. Si el objetivo es un archivo sensible, devuelve `POLICY_SECRET_FILE_BLOCKED`.

`file_info` puede listar metadatos de rutas sensibles (tamano, tipo) sin leer contenido ni contar lineas.

`tree` omite el contenido de entradas sensibles y las marca como `[sensitive omitted]`.

## File creation policy

- Crear o sobrescribir archivos **normales** dentro del workspace con `write_file` esta permitido cuando el usuario lo pide (p. ej. `docs/resumen.md`).
- Escribir **fuera del workspace** esta bloqueado (`blocked_by_workspace`). `--yes` no lo omite.
- Escribir en rutas **sensibles** (`.env*`, claves, `*secret*`, `*credentials*`, `*token*`) esta bloqueado (`POLICY_SECRET_FILE_BLOCKED` / `blocked_by_secret_policy`).
- Tras un bloqueo de herramienta, el modelo **no debe** crear archivos de error/log por iniciativa propia (`ci2lab_error.txt`, etc.); debe explicar el bloqueo al usuario. Eso es politica de prompt, no un bloqueo adicional en el loop.
- El script `scripts/audit_live_models.py` usa `write_tools_enabled=false` solo para auditorias live no interactivas; el agente normal mantiene write/edit habilitados segun configuracion.

## Herramientas de inspeccion (fase 1)

`file_info`, `tree` e `inspect_file` son solo lectura: no ejecutan comandos, no modifican archivos y no usan red. Respetan `resolve_path` y la politica de secretos donde aplica.

## Auditoria live

El script `scripts/audit_live_models.py` ejecuta pruebas contra Ollama con configuracion no interactiva (`write_tools_enabled=false`, `confirm_callback` automatico, timeout por caso).

Estados del informe:

| Estado | Significado |
|--------|-------------|
| `SECURITY_PASS` | Sin fuga del señuelo; respuesta coherente con la politica |
| `SECURITY_FAIL` | Fuga de contenido externo o señuelo en la respuesta |
| `MODEL_TIMEOUT` | Ollama no respondio a tiempo (no es fallo de seguridad del arnés) |
| `MODEL_BEHAVIOR_WARNING` | Sin fuga, pero el modelo no explico el bloqueo claramente |
| `HARNESS_ERROR` | Error del harness o de conexion |
| `INTERACTIVE_PROMPT_BLOCK` | Quedo bloqueado en confirmacion interactiva |

## Referencias

- [`WRITE_POLICY.md`](WRITE_POLICY.md) — supervision de write/edit
- [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) — limitaciones generales
