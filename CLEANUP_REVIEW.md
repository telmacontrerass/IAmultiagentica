# Cleanup review

Cleanup pass done 2026-07-09. All items were decided by the team and applied.
Everything deleted remains recoverable from git history.

## Applied decisions

**Deleted** (with all inbound references fixed):

- `Quarry-Yard-main.zip`, `ci2lab/catalog/.gitkeep`
- `audit/repo_cleanup/repo_cleanup_report.md` (folder removed)
- `docs/stashed_changes_concepts.md` — note: concepts G (`_infer_allowed_write_roots`
  folder-scope inference) and H (`policy_v1` engine rename) were never implemented; the
  deleted file (git history) is the only written record of those plans.
- `docs/reports/2026-06-16_live_fact_lookup_and_web_fallback.md` (folder removed)
- `docs/HARDWARE_ROUTER_HANDOFF.md` — links removed from `README.md` and
  `ci2lab/contracts/README.md`; citation in `PAIN_POINTS.md` marked historical.
- `docs/audits/` (all 4 snapshot files; folder removed) — links removed from
  `docs/WRITE_POLICY.md`. The scripts that write into `docs/audits/` or `audit/reports/`
  (`ci2lab/scripts/audit_live_models.py`, `audit/redteam/run_redteam.py`,
  `audit/redteam/run_security_regression.py`) all `mkdir` their output path, so they
  keep working.
- `audit/reports/floren_redteam_report.md` + `redteam_results.json` (folder removed;
  `audit/reports/` was already gitignored, so future reports stay local)
- `docs/NEXT_AGENT_ROADMAP.md`
- All Quarto HTML renders + asset folders: `COMANDOS.html` + `COMANDOS_files/`,
  `PAPER_DIRECTION.html` + `PAPER_DIRECTION_files/`, `docs/BENCHMARKING.html` +
  `docs/BENCHMARKING_files/`, `docs/KNOWN_LIMITATIONS.html` +
  `docs/KNOWN_LIMITATIONS_files/`. The `.md` sources are the single source of truth;
  regenerate locally with `quarto render <file>.md` when a shareable page is needed.
  `.gitignore` now blocks re-committing renders (`/*.html`, `docs/*.html`, `*_files/`).
  Note: `PAPER_DIRECTION.md` is gitignored (local-only), so with its render gone the
  paper-direction document now lives **only** on the machines that have the `.md` —
  the quotes inside `PAIN_POINTS.md` are the only committed excerpts.
- `.pytest_tmp_*` leftover dirs at the repo root (deleted manually by the team;
  `.gitignore` now has `.pytest_tmp_*/`).

**Kept**: `benchmarks/results/benchmark_report.xlsx` (team decision).

**Moved**: `20260217_rudiger_user_instructions.md` → `docs/` (USAGE_MANUAL pointer updated).
