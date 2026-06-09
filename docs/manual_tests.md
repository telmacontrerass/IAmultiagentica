# Pruebas manuales — Ci2Lab

Checklist para validar el arnés tras cambios. Requiere Ollama en marcha con un modelo instalado (p. ej. `llama3.1:8b`).

Para regresión automatizada, ver también [`regression_checklist.md`](regression_checklist.md) y [`evals.md`](evals.md).

## Preparación

```bash
cd IAmultiagentica
.venv\Scripts\activate
pip install -e ".[dev]"
ci2lab doctor
```

## 1. Turno básico con logging

```bash
python -m ci2lab.cli --no-stream --yes "lista los archivos del directorio actual"
```

Verificar:

- [ ] Respuesta en terminal sin error fatal
- [ ] Carpeta nueva en `runs/YYYY-MM-DD_HHMMSS_<id>/`
- [ ] `run_summary.json` con `model`, `workspace`, `tools_used` (esperado: `ls` o similar)
- [ ] `tool_calls.jsonl` con al menos una línea si el modelo usó herramientas
- [ ] `conversation.json` con mensajes `system`, `user`, `assistant`, `tool`
- [ ] `final_answer.md` con texto de respuesta
- [ ] `config_snapshot.json` con configuración efectiva

## 2. Sin logging

```bash
python -m ci2lab.cli --no-log --no-stream --yes "lista los archivos"
```

Verificar:

- [ ] No se crea carpeta nueva en `runs/` (comparar timestamp antes/después)
- [ ] El agente responde igual que con logging

## 3. Workspace y runs-dir personalizados

```bash
python -m ci2lab.cli --workspace . --runs-dir ./_test_runs --no-stream --yes "hola"
```

Verificar:

- [ ] Carpeta bajo `_test_runs/` (no `runs/` por defecto)
- [ ] `run_summary.json` → `workspace` apunta al directorio actual absoluto

Limpiar: `rm -r _test_runs` (o borrar manualmente en Windows).

## 4. Errores Ollama

Con Ollama **detenido**:

```bash
python -m ci2lab.cli "hola"
```

Verificar:

- [ ] Mensaje accionable (conectar, `ollama serve`, `ci2lab doctor`)
- [ ] Exit code distinto de 0

## 5. Blocklist bash

En REPL o con un prompt que pida `rm -rf /` vía bash:

Verificar:

- [ ] Comando bloqueado aunque uses `--yes`
- [ ] El agente continúa (error devuelto al modelo, no crash)

## 6. Config YAML

Crear `ci2lab.yaml` temporal:

```yaml
model: llama3.1:8b
runs_dir: runs
log_runs: true
```

```bash
python -m ci2lab.cli --no-stream --yes "di hola"
```

Verificar:

- [ ] Run creado bajo `runs/`
- [ ] `config_snapshot.json` refleja el modelo configurado

## 7. Edición supervisada (write/edit)

Las tools `write_file` y `edit_file` están habilitadas en **modo supervisado**: diff preview obligatorio por defecto, aprobación humana, registro en `runs/`. Ver [`WRITE_POLICY.md`](WRITE_POLICY.md).

Crear `test_edit.txt` con contenido `version 1`.

```bash
python -m ci2lab.cli --no-stream "cambia test_edit.txt de version 1 a version 2 con edit_file"
```

Verificar:

- [ ] Panel de preview con diff unificado antes de escribir
- [ ] Si respondes `n`, el archivo no cambia
- [ ] Si respondes `s`, el archivo se actualiza
- [ ] `tool_calls.jsonl` → `outcome: approved` o `denied`

Probar `--yes` con preview obligatorio:

```bash
python -m ci2lab.cli --no-stream --yes "usa edit_file en test_edit.txt ..."
```

Verificar:

- [ ] **Sigue pidiendo confirmación** (o muestra preview y pide `[s/N]`) con `require_diff_preview: true` por defecto

Deshabilitar escritura en `ci2lab.yaml`:

```yaml
write_tools_enabled: false
```

Verificar:

- [ ] `write_file` / `edit_file` devuelven error al modelo sin modificar archivos
- [ ] `tool_calls.jsonl` → `outcome: blocked_by_config`

## 8. Evaluación práctica (evals)

```bash
python -m ci2lab.evals.run
```

Verificar:

- [ ] 7/7 tareas PASS en modo mock (sin Ollama)
- [ ] Carpeta `evals/results/YYYY-MM-DD_HHMMSS/` con `summary.json` y `results.jsonl`
- [ ] `runs/<task_id>/tool_calls.jsonl` registra tools por tarea
- [ ] Exit code 0

Una tarea concreta:

```bash
python -m ci2lab.evals.run --task 006_edit_file_approved
```

Modo live (opcional, requiere Ollama):

```bash
python -m ci2lab.evals.run --live --model llama3.1:8b --task 001_list_files
```

## 9. Entrypoints

```bash
python -m ci2lab.cli --help
python -m ci2lab --help
python -m ci2lab.cli --workspace . --help
```

Verificar flags `--workspace`, `--runs-dir`, `--no-log` en la ayuda.
