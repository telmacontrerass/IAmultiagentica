# Manual tests — Ci2Lab

A checklist to validate the harness after changes. Requires Ollama running with an installed model (e.g. `llama3.1:8b`).

For automated regression, see also [`regression_checklist.md`](regression_checklist.md) and [`evals.md`](evals.md).

## Setup

```bash
cd IAmultiagentica
.venv\Scripts\activate
pip install -e ".[dev]"
ci2lab doctor
```

## 1. Basic turn with logging

```bash
python -m ci2lab.cli --no-stream --yes "list the files in the current directory"
```

Check:

- [ ] A response in the terminal with no fatal error
- [ ] A new folder under `runs/YYYY-MM-DD_HHMMSS_<id>/`
- [ ] `run_summary.json` with `model`, `workspace`, `tools_used` (expected: `ls` or similar)
- [ ] `tool_calls.jsonl` with at least one line if the model used tools
- [ ] `conversation.json` with `system`, `user`, `assistant`, `tool` messages
- [ ] `final_answer.md` with the response text
- [ ] `config_snapshot.json` with the effective configuration

## 2. No logging

```bash
python -m ci2lab.cli --no-log --no-stream --yes "list the files"
```

Check:

- [ ] No new folder is created under `runs/` (compare timestamps before/after)
- [ ] The agent responds the same as with logging

## 3. Custom workspace and runs-dir

```bash
python -m ci2lab.cli --workspace . --runs-dir ./_test_runs --no-stream --yes "hello"
```

Check:

- [ ] A folder under `_test_runs/` (not the default `runs/`)
- [ ] `run_summary.json` → `workspace` points to the current directory's absolute path

Cleanup: `rm -r _test_runs` (or delete manually on Windows).

## 4. Ollama errors

With Ollama **stopped**:

```bash
python -m ci2lab.cli "hello"
```

Check:

- [ ] An actionable message (connect, `ollama serve`, `ci2lab doctor`)
- [ ] A non-zero exit code

## 5. Bash blocklist

In the REPL, or with a prompt asking to run `rm -rf /` via bash:

Check:

- [ ] The command is blocked even with `--yes`
- [ ] The agent continues (the error is returned to the model, no crash)

## 6. YAML config

Create a temporary `ci2lab.yaml`:

```yaml
model: llama3.1:8b
runs_dir: runs
log_runs: true
```

```bash
python -m ci2lab.cli --no-stream --yes "say hello"
```

Check:

- [ ] A run is created under `runs/`
- [ ] `config_snapshot.json` reflects the configured model

## 7. Supervised editing (write/edit)

The `write_file` and `edit_file` tools are enabled in **supervised mode**: a mandatory diff preview by default, human approval, and a record under `runs/`. See [`WRITE_POLICY.md`](WRITE_POLICY.md).

Create `test_edit.txt` with the content `version 1`.

```bash
python -m ci2lab.cli --no-stream "change test_edit.txt from version 1 to version 2 with edit_file"
```

Check:

- [ ] A preview panel with a unified diff before writing
- [ ] If you answer `n`, the file does not change
- [ ] If you answer `y`, the file is updated
- [ ] `tool_calls.jsonl` → `outcome: approved` or `denied`

Test `--yes` with the mandatory preview:

```bash
python -m ci2lab.cli --no-stream --yes "use edit_file on test_edit.txt ..."
```

Check:

- [ ] It **still asks for confirmation** (or shows the preview and asks `[y/N]`) with the default `require_diff_preview: true`

Disable writing in `ci2lab.yaml`:

```yaml
write_tools_enabled: false
```

Check:

- [ ] `write_file` / `edit_file` return an error to the model without modifying files
- [ ] `tool_calls.jsonl` → `outcome: blocked_by_config`

## 8. Practical evaluation (evals)

```bash
python -m ci2lab.evals.run
```

Check:

- [ ] All tasks PASS in mock mode (no Ollama)
- [ ] A folder `evals/results/YYYY-MM-DD_HHMMSS/` with `summary.json` and `results.jsonl`
- [ ] `runs/<task_id>/tool_calls.jsonl` records tools per task
- [ ] Exit code 0

A single task:

```bash
python -m ci2lab.evals.run --task 006_edit_file_approved
```

Live mode (optional, requires Ollama):

```bash
python -m ci2lab.evals.run --live --model llama3.1:8b --task 001_list_files
```

## 9. Hardware and router

```bash
ci2lab hardware
ci2lab hardware --json
ci2lab models recommend
ci2lab models recommend "I want to program in Python"
ci2lab models install qwen2.5-coder-1.5b
```

Check:

- [ ] `hardware` shows RAM, VRAM, GPU, `inference_budget_gb`, `hardware_tier`
- [ ] `models recommend` lists only models that fit the budget
- [ ] With a coding prompt, the coder models appear at the top
- [ ] `models install` shows `ollama pull`, `ollama run`, and `ci2lab --model … chat`

**Known limitation:** `ci2lab chat` does not use the router automatically; `--model` must come before the subcommand. See [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).

## 10. Entry points

```bash
python -m ci2lab.cli --help
python -m ci2lab --help
python -m ci2lab.cli --workspace . --help
```

Check the `--workspace`, `--runs-dir`, `--no-log` flags appear in the help.
