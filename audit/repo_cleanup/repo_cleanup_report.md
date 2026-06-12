# Repo cleanup audit report

Generated: 2026-06-12 (local audit, no files deleted)

Machine: Windows | Repo: IAmultiagentica | Branch: security work in progress

## Executive summary

- **No artifact directories are tracked in git** (`artifacts/`, `audit/deterministic_claude/`,
  `audit/live_claude/`, `tmp/`, `.ci2lab/` have 0 tracked files). They are **not** entering
  git accidentally today, but **most are also not in `.gitignore`**, so they appear as `??` in
  `git status` and could be committed by mistake.
- **`runs/` is correctly gitignored** (284 files, ~0.62 MB locally) but accumulates agent run logs.
- **Largest safe-delete buckets**: `runs/` (ignored), `artifacts/` (72 files), `tmp/` (65 files),
  `audit/live_claude/` (74 files), `audit/deterministic_claude/` (12 files), `.ci2lab/` (1 file).
- **Untracked source code** (security module, scripts, tests, docs) is **KEEP** -- must be
  committed, not deleted.
- **Recommended next step**: update `.gitignore`, then phased local delete of generated dirs.

---

## 1. Git inspection (executed)

### git status --short (summary)

| Kind | Count | Notes |
|------|-------|-------|
| Modified tracked (`M`) | 20 | Source/docs/tests -- KEEP, not cleanup targets |
| Untracked (`??`) | ~60 top-level entries | Mix of source (KEEP) and artifacts (DELETE_SAFE/IGNORE) |

### git clean -nd (untracked, not ignored)

Would remove **all untracked paths**, including **source that must be kept**:

- Entire `ci2lab/security/` package (18 modules)
- `ci2lab/cli_permissions.py`, `ci2lab/harness/security_profiles.py`, etc.
- All new `scripts/*.py` and `tests/test_*.py`
- `docs/CLAUDE_EXPERIMENTAL_VALIDATION.md`
- Plus generated: `artifacts/`, `audit/deterministic_claude/`, `audit/live_claude/`, `tmp/`, etc.

**WARNING**: Never run `git clean -fd` without reviewing; it would delete uncommitted source.

### git clean -ndX (ignored only)

Would remove (safe cache/runtime, already gitignored):

| Path | Role |
|------|------|
| `.pytest_cache/` | pytest cache (5 files) |
| `__pycache__/` (multiple) | Python bytecode |
| `.venv/` | local virtualenv |
| `.env` | local secrets (root) |
| `audit/redteam_sandbox/.env` | sandbox env (ignored) |
| `evals/results/` | eval output |
| `runs/` | agent run logs (57+ session dirs, ~0.62 MB) |
| `tmp/harness_write_eval/*/runs/` | nested run logs inside tmp workspaces |

---

## 2. Accidental git tracking check

| Directory | Tracked files | In .gitignore | Risk |
|-----------|---------------|---------------|------|
| `artifacts/` | 0 | **No** | Medium -- shows as untracked, could be `git add` by mistake |
| `audit/deterministic_claude/` | 0 | **No** | Medium |
| `audit/live_claude/` | 0 | **No** | Medium |
| `tmp/` | 0 | **No** | Medium |
| `.ci2lab/` | 0 | **No** | Medium |
| `runs/` | 0 | **Yes** (`runs/`) | Low -- ignored correctly |
| `.pytest_cache/` | 0 | **Yes** | Low |
| `__pycache__/` | 0 | **Yes** | Low |
| `evals/results/` | 0 | **Yes** | Low |
| `htmlcov/`, `.coverage` | absent | N/A | Not present locally |

**Tracked under `audit/` (intentional fixtures/scripts):**

- `audit/redteam/run_redteam.py` -- KEEP (script)
- `audit/redteam_sandbox/*` -- KEEP (redteam fixtures: fake secrets, dos_many, etc.)
- `audit/reports/floren_redteam_report.md`, `redteam_results.json` -- KEEP (committed reports)

---

## 3. Size inventory (local disk)

| Path | Files | Approx size | Default class |
|------|-------|-------------|---------------|
| `runs/` | 284 | 0.62 MB | DELETE_SAFE (ignored) |
| `artifacts/` | 72 | 0.02 MB | DELETE_SAFE + IGNORE |
| `tmp/` | 65 | 0.11 MB | DELETE_SAFE + IGNORE |
| `audit/live_claude/` | 74 | 0.04 MB | DELETE_SAFE + IGNORE |
| `audit/deterministic_claude/` | 12 | 0.08 MB | DELETE_SAFE + IGNORE |
| `audit/reports/` (untracked new) | 2 | part of 0.08 MB | REVIEW |
| `.ci2lab/` | 1 | 0.07 MB | DELETE_SAFE + IGNORE |
| `.pytest_cache/` | 5 | 0.04 MB | DELETE_SAFE (ignored) |

---

## 4. Classification tables

Legend:

- **KEEP** -- source, tests, or docs to preserve (commit, do not delete)
- **DELETE_SAFE** -- generated/reproducible; safe to remove locally
- **IGNORE** -- add to `.gitignore` to stop cluttering `git status`
- **REVIEW** -- manual decision required

### 4.1 Generated artifacts (DELETE_SAFE + IGNORE)

| Path | Files | Produced by | Class | Reason |
|------|-------|-------------|-------|--------|
| `artifacts/harness_write_eval/2026-06-12_104154/` | 72 | `scripts/run_harness_write_eval.py` | DELETE_SAFE + IGNORE | Per-case stdout, diff, verdict JSON |
| `audit/deterministic_claude/2026-06-12_*` (4 runs) | 12 | `scripts/audit_claude_deterministic.py` | DELETE_SAFE + IGNORE | results.csv, summary.json, report.md |
| `audit/live_claude/2026-06-12_*` (3 runs) | ~72 | `scripts/audit_claude_experimental_live.py` | DELETE_SAFE + IGNORE | stdout/stderr, security_audit.jsonl copies |
| `runs/` (all subdirs) | 284 | `ci2lab chat/agent` RunLogger | DELETE_SAFE | Already in .gitignore; agent session logs |
| `runs/security_comparison/2026-06-12_*` | few | `scripts/compare_security_engines.py` | DELETE_SAFE | comparison.csv/md |
| `runs/opencode_config_comparison/` | few | `scripts/compare_opencode_configs.py` | DELETE_SAFE | config diff output |
| `tmp/harness_write_eval/` | 65 | harness write eval workspaces | DELETE_SAFE + IGNORE | Ephemeral workspaces + nested `runs/` |
| `.ci2lab/security_audit.jsonl` | 1 | runtime audit persist | DELETE_SAFE + IGNORE | Local audit log (~77 KB) |
| `.pytest_cache/` | 5 | pytest | DELETE_SAFE | Already ignored |
| `**/__pycache__/` | many | Python | DELETE_SAFE | Already ignored |

**Recommended commands (NOT executed):**

```powershell
# Phase 1 -- generated output dirs (untracked, not source)
Remove-Item -Recurse -Force artifacts, tmp, .ci2lab
Remove-Item -Recurse -Force audit\deterministic_claude, audit\live_claude

# Phase 2 -- ignored runtime (safe; regenerates on next run)
Remove-Item -Recurse -Force runs, .pytest_cache
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
```

### 4.2 Cache / temp (DELETE_SAFE)

| Path | Class | Notes |
|------|-------|-------|
| `.venv/` | DELETE_SAFE | Recreate with pip/conda; already ignored |
| `.env` (root) | REVIEW | Secrets -- do not delete if needed; never commit |
| `audit/redteam_sandbox/.env` | DELETE_SAFE | Ignored; sandbox only |

### 4.3 Source code -- KEEP (untracked, must NOT delete)

| Path | Class | Reason |
|------|-------|--------|
| `ci2lab/security/` (18 modules) | **KEEP** | Core security implementation |
| `ci2lab/cli_permissions.py` | **KEEP** | CLI permissions dashboard |
| `ci2lab/harness/security_profiles.py` | **KEEP** | Security profiles |
| `ci2lab/evals/harness_write_eval.py` | **KEEP** | Eval harness code |
| `scripts/audit_claude_deterministic.py` | **KEEP** | CI script |
| `scripts/audit_claude_experimental_live.py` | **KEEP** | Live audit script |
| `scripts/compare_security_engines.py` | **KEEP** | Comparison script |
| `scripts/compare_opencode_configs.py` | **KEEP** | Config comparison |
| `scripts/security_gate_check.py` | **KEEP** | Gate dry-run CLI |
| `scripts/security_config_export.py` | **KEEP** | Config export |
| `scripts/run_harness_write_eval.py` | **KEEP** | Write eval runner |
| `tests/test_security_*.py` (6 files) | **KEEP** | Security tests |
| `tests/test_claude_*.py` (3 files) | **KEEP** | Claude experimental tests |
| `tests/test_opencode_*.py` (2 files) | **KEEP** | OpenCode tests |
| `tests/test_approval_prompt.py` | **KEEP** | UX tests |
| `tests/test_session_permissions.py` | **KEEP** | Session approval tests |
| `tests/test_permissions_*.py` (2 files) | **KEEP** | Permissions tests |
| `tests/test_secret_files_v02.py` | **KEEP** | V-02 tests |
| `tests/harness_write_eval/` | **KEEP** | Static eval tests |
| `audit/redteam/run_security_regression.py` | **KEEP** | Regression script |

### 4.4 Docs -- KEEP

| Path | Class | Reason |
|------|-------|--------|
| `docs/CLAUDE_EXPERIMENTAL_VALIDATION.md` | **KEEP** | Validation checklist (untracked, should commit) |
| `docs/SECURITY_POLICY.md` | **KEEP** | Modified tracked |
| `docs/KNOWN_LIMITATIONS.md` | **KEEP** | Modified tracked |
| `README.md` | **KEEP** | Modified tracked |

### 4.5 REVIEW -- manual decision

| Path | Class | Reason | Suggestion |
|------|-------|--------|------------|
| `TRABAJO DE INGENIERIA ENERGETICA - HITO 1.pdf` | **REVIEW** | Academic PDF at repo root; unrelated to code | Move outside repo or add `*.pdf` ignore at root |
| `inside.txt` | **DELETE_SAFE** | 8 bytes test stub ("inside"); likely compare_security_engines leftover | Delete |
| `opencode.json` | **REVIEW** | Local permission config sample (173 B) | KEEP as example in `docs/` or add to `.gitignore` if personal |
| `audit/live_claude/P2_9_SUMMARY.md` | **REVIEW** | Untracked summary snapshot | KEEP in repo as doc or regenerate from script |
| `audit/live_claude/P3_0_VALIDATION_SUMMARY.md` | **REVIEW** | Untracked summary snapshot | Same as above |
| `audit/reports/floren_security_regression_report.md` | **REVIEW** | New untracked report | Commit if canonical, else DELETE_SAFE |
| `audit/reports/floren_security_regression_results.json` | **REVIEW** | New untracked JSON | Same |
| `audit/redteam_sandbox/docs/tokenization.md` | **KEEP** | V-02 documentation fixture | Commit with redteam work |
| `audit/redteam_sandbox/tokenizer.py` | **KEEP** | V-02 test fixture | Commit |
| `audit/redteam_sandbox/tests/test_tokenizer.py` | **KEEP** | V-02 test | Commit |
| `audit/redteam_sandbox/generated_ok.md` | **DELETE_SAFE** | Generated edit output ("# ok edited") | Delete |
| `audit/redteam_sandbox/id_ed25519` | **KEEP** | Secret-name fixture (like tracked `id_rsa`) | Commit as fixture, never real key |
| `.vscode/settings.json` | **KEEP** | Already tracked | IDE settings |

### 4.6 Tracked redteam sandbox (KEEP -- not cleanup)

Already versioned fake secrets and stress files under `audit/redteam_sandbox/` (~80+ files).
These are **intentional test fixtures**, not temp artifacts. Do not delete.

---

## 5. Detailed untracked table (grouped)

| Group | Representative paths | Class | Motivo |
|-------|---------------------|-------|--------|
| Harness write eval output | `artifacts/harness_write_eval/2026-06-12_104154/**` | DELETE_SAFE + IGNORE | Script output; reproducible |
| Deterministic audit | `audit/deterministic_claude/2026-06-12_*/{report.md,results.csv,summary.json}` | DELETE_SAFE + IGNORE | 4 timestamp dirs |
| Live audit | `audit/live_claude/2026-06-12_*/{*.stdout.txt,*.stderr.txt,results.csv,...}` | DELETE_SAFE + IGNORE | 3 timestamp dirs |
| Temp workspaces | `tmp/harness_write_eval/*/{hello.txt,config.json,runs/,...}` | DELETE_SAFE + IGNORE | Eval sandboxes |
| Runtime audit | `.ci2lab/security_audit.jsonl` | DELETE_SAFE + IGNORE | Agent audit persist |
| Security source | `ci2lab/security/*.py` | KEEP | Product code |
| Security tests | `tests/test_*security*`, `tests/test_claude_*`, ... | KEEP | Test suite |
| Security scripts | `scripts/audit_*`, `scripts/compare_*`, `scripts/security_*` | KEEP | CI/dev tooling |
| Root clutter | `inside.txt` | DELETE_SAFE | Accidental test file |
| Root PDF | `TRABAJO...HITO 1.pdf` | REVIEW | Non-project asset |
| Local config | `opencode.json` | REVIEW | Dev permission config |

---

## 6. Proposed .gitignore additions

Current `.gitignore` covers: `__pycache__/`, `.pytest_cache/`, `.venv/`, `*.log`, `.env`, `runs/`, `evals/results/`.

**Missing patterns** (recommended append):

```gitignore
# --- CI2Lab generated output (add) ---
artifacts/
tmp/
.ci2lab/

# Security / harness audit output (regenerable)
audit/deterministic_claude/
audit/live_claude/

# Optional: keep summary markdown but ignore timestamp dirs
# !audit/live_claude/P*_SUMMARY.md

# Local dev configs (optional)
/opencode.json
/inside.txt

# IDE / tooling (optional; .vscode/settings.json is already tracked)
# .vscode/

# Coverage (if used later)
htmlcov/
.coverage
```

**Do NOT add to gitignore** (should be committed):

- `ci2lab/security/`
- `scripts/`, new `tests/`
- `docs/CLAUDE_EXPERIMENTAL_VALIDATION.md`
- `audit/redteam/run_security_regression.py`
- New `audit/redteam_sandbox/` fixtures (tokenizer, id_ed25519, tests)

---

## 7. Phased safe cleanup plan

### Phase 0 -- Preparation (no deletes)

1. Commit or stash all **KEEP** source (security module, tests, scripts, docs).
2. Apply `.gitignore` additions above.
3. Re-run `git status --short` to confirm only expected `??` remain.

### Phase 1 -- Delete reproducible artifacts (local only)

Targets: `artifacts/`, `tmp/`, `.ci2lab/`, `audit/deterministic_claude/`, `audit/live_claude/2026-06-12_*`, `inside.txt`, `audit/redteam_sandbox/generated_ok.md`

```powershell
Remove-Item -Recurse -Force artifacts, tmp, .ci2lab -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force audit\deterministic_claude -ErrorAction SilentlyContinue
Get-ChildItem audit\live_claude -Directory -Filter '2026-06-12_*' | Remove-Item -Recurse -Force
Remove-Item -Force inside.txt, audit\redteam_sandbox\generated_ok.md -ErrorAction SilentlyContinue
```

### Phase 2 -- Purge ignored runtime cache

```powershell
Remove-Item -Recurse -Force runs, .pytest_cache -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
```

### Phase 3 -- Manual review

- `TRABAJO DE INGENIERIA ENERGETICA - HITO 1.pdf` -- relocate or ignore
- `opencode.json` -- commit as example or ignore
- `audit/reports/floren_security_regression_*` -- commit or delete
- `audit/live_claude/P2_9_SUMMARY.md`, `P3_0_VALIDATION_SUMMARY.md` -- commit to `docs/` or `audit/` tracked path

### Phase 4 -- Verify

```powershell
python -m ci2lab doctor
pytest tests/ -q
python scripts/audit_claude_deterministic.py
python scripts/compare_security_engines.py
```

---

## 8. What must never be cleaned

| Category | Examples |
|----------|----------|
| Source | `ci2lab/`, `scripts/` (except generated output paths) |
| Tests | `tests/` (all `test_*.py`) |
| Docs | `docs/`, `README.md` |
| Redteam fixtures (tracked) | `audit/redteam_sandbox/id_rsa`, `credentials.json`, `dos_many/` |
| Redteam fixtures (untracked, should commit) | `tokenizer.py`, `id_ed25519`, `tests/test_tokenizer.py` |
| Versioned reports | `audit/reports/floren_redteam_report.md`, `redteam_results.json` |

---

## 9. Acceptance checklist

| Criterion | Status |
|-----------|--------|
| No files deleted during this audit | **PASS** |
| Report identifies safe cleanup targets | **PASS** |
| `artifacts/`, `audit/*_claude`, `tmp/` not in git index | **PASS** (0 tracked) |
| `runs/` gitignored correctly | **PASS** |
| Risk of accidental commit of artifacts | **NOTED** -- add `.gitignore` patterns |
| Phased cleanup plan provided | **PASS** |

---

*End of report. Generated by local inspection only; no `Remove-Item` or `git clean` was executed.*
