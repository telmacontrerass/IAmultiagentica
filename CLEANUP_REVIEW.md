# Cleanup review — candidates that need a human decision

Generated 2026-07-09 during a repo cleanup pass (after pulling `origin/main` at `282be84`).

**Already removed** (100% safe, no functionality touched):

| Removed | Why it was safe |
|---------|-----------------|
| `Quarry-Yard-main.zip` (repo root) | One-time import archive. Its contents were already salvaged into `ci2lab/harness/yard/builtin/` (see `ci2lab/harness/yard/__init__.py`). `git grep` finds **zero** references to the file; no code opens it. CLAUDE.md forbids data files at the repo root. Still recoverable from git history. |
| `ci2lab/catalog/.gitkeep` | Placeholder from before `models.json` existed in that directory; the directory is no longer empty, so the keep-file does nothing. |

Everything below **looks like one-time-use material but could not be deleted with 100% certainty** — mostly because `docs/USAGE_MANUAL.md` §15 explicitly marks several of them "no borrar sin revisión del equipo", or because living docs still link to them. Decide per item; the "If you delete it" column lists the follow-up edits needed so nothing dangles.

## 1. Completed-task / one-time documents

| File | Evidence it's one-time-use | Why not 100% sure | If you delete it |
|------|---------------------------|-------------------|------------------|
| `audit/repo_cleanup/repo_cleanup_report.md` | One-time cleanup audit dated 2026-06-12. Every recommendation has since been applied: the proposed `.gitignore` patterns (`artifacts/`, `tmp/`, `.ci2lab/`, `audit/*_claude/`, `inside.txt`, `opencode.json`) are all in `.gitignore` today, and the scratch files it flagged (`inside.txt`, `opencode.json`) no longer exist. | `docs/USAGE_MANUAL.md` §15 lists `audit/repo_cleanup/` under "Histórico — no borrar sin revisión". | Delete the whole `audit/repo_cleanup/` folder and remove the `audit/repo_cleanup/` bullet at `docs/USAGE_MANUAL.md` (§15, "Histórico"). |
| `20260217_rudiger_user_instructions.md` (repo root) | Usage/environment guide for the RUDIGER GPU workstation (SSH, conda envs, Docker). Not about this codebase at all — someone's environment notes dropped at the repo root. | It documents the team's shared Linux server (which hosts multi-agent work), so it may still be operationally useful; USAGE_MANUAL flags it "archivo histórico de referencia". If kept, consider moving it to `docs/` or a team wiki instead of the repo root. | Delete it and remove its bullet in `docs/USAGE_MANUAL.md` §15. |
| `docs/stashed_changes_concepts.md` | Triage report (2026-06-30) of 4 git stashes on someone's machine. Verified against today's code: Concepts A–E **already landed in main** (`_calls_from_json_value`, `_append_fenced_tool_results`, `_contract_expected_from_prompt`, `classify_file_creation_contract`/`contract_validation`, `tool_trace_failed`). | Concepts **G** (`_infer_allowed_write_roots` folder-scope inference) and **H** (`policy_v1` engine rename) are **not** in main — this file is the only written record of those two plans. Also flagged "no borrar sin revisión" in USAGE_MANUAL. | Move the G/H sections into `docs/NEXT_AGENT_ROADMAP.md` (or decide they're abandoned), then delete + remove the USAGE_MANUAL bullet. |
| `docs/reports/2026-06-16_live_fact_lookup_and_web_fallback.md` | One-time work report of a finished task; self-labeled "Historical snapshot; may not reflect the current implementation". Nothing links to it. | USAGE_MANUAL §14 protects the `docs/reports/` folder ("no borrar sin revisión"). It's the only file in that folder. | Delete it (and the now-empty folder), and drop the `docs/reports/` row from the table in `docs/USAGE_MANUAL.md` §14. |
| `docs/HARDWARE_ROUTER_HANDOFF.md` | Handoff spec for the hardware/router component; its own status table shows nearly everything "Implemented" — the handoff happened. | Still **referenced** by `README.md`, `ci2lab/contracts/README.md`, `PAIN_POINTS.md`, and `docs/audits/current_harness_flow_audit.md`; and it tracks genuinely pending items (`runtime/ensure.py`, per-model live validation). | Recommend **keep**. If removed anyway: move the "What is left" section to `docs/NEXT_AGENT_ROADMAP.md` and fix all four inbound links. |
| `docs/audits/` (4 files: `current_harness_flow_audit`, `live_eval_status`, `run_logging`, `write_edit_tools_status`) | All four are point-in-time snapshots from 2026-06-09, each banner-labeled "Historical snapshot". | Cross-referenced from a living doc: `docs/WRITE_POLICY.md` links to `write_edit_tools_status.md`. Also `ci2lab/scripts/audit_live_models.py` writes its default report into `docs/audits/`. USAGE_MANUAL protects the folder. | If pruned, keep (or inline into WRITE_POLICY) `write_edit_tools_status.md`, fix the WRITE_POLICY link, and change the default `--output` path in `ci2lab/scripts/audit_live_models.py`. |
| `audit/reports/floren_redteam_report.md` + `redteam_results.json` | Dated one-time red-team reports. Oddly, `audit/reports/` is in `.gitignore` yet these two are still tracked. | No code or test references them (checked: `redteam_results`/`floren` appear nowhere in `tests/`), but USAGE_MANUAL explicitly protects `audit/` as red-team history for future decisions. | `git rm` both if the team no longer needs the record. |
| `docs/NEXT_AGENT_ROADMAP.md` | Reads like a handoff note ("next agent"), numbering starts at §4 (§1–3 presumably done and pruned). | The remaining items (`run_tests` tool, repo map, vector memory) are **not implemented** — this is a live backlog, not a completed task. | Recommend **keep** (or rename to a neutral `docs/ROADMAP.md`). |

## 2. Generated artifacts committed to git

| Path | Issue | Why not 100% sure | If you delete it |
|------|-------|-------------------|------------------|
| `COMANDOS.html` + `COMANDOS_files/` | Quarto render of `COMANDOS.md` — fully regenerable (`quarto render COMANDOS.md`). Each `_files/` dir vendors a full copy of Bootstrap (~2 MB). | The team may deliberately want browsable HTML in the repo — `docs/KNOWN_LIMITATIONS.html` was committed just 2 days ago. | `git rm -r` the html + `_files/` dir; optionally add `*_files/` and the specific `.html` renders to `.gitignore`. Same for the other three below. |
| `docs/BENCHMARKING.html` + `docs/BENCHMARKING_files/` | Same — render of `docs/BENCHMARKING.md`. | Same. | Same. |
| `docs/KNOWN_LIMITATIONS.html` + `docs/KNOWN_LIMITATIONS_files/` | Same — render of `docs/KNOWN_LIMITATIONS.md`, committed 2026-07-07. | Recently and deliberately committed. | Same. |
| `PAPER_DIRECTION.html` + `PAPER_DIRECTION_files/` | **Special case.** The source `PAPER_DIRECTION.md` is deliberately gitignored ("Paper planning — local strategy notes, not for the repo"), yet its HTML render **is** committed — contradicting that intent. | Deleting the HTML would remove the **only committed copy** of a doc that `PAIN_POINTS.md` quotes extensively (its `PAPER_DIRECTION.md` links are already broken for anyone without the local file). | Team must pick one: (a) commit `PAPER_DIRECTION.md` and drop the render, (b) keep the render as the shared copy, or (c) treat the whole topic as private and delete the render too (fixing `PAIN_POINTS.md` links). |
| `benchmarks/results/benchmark_report.xlsx` | Generated binary output of bench runs, force-tracked via a `!` exception in `.gitignore` (added 2026-07-07). Binary churn on every re-run. | Explicitly and recently un-ignored — that's a deliberate choice, and `benchmarks/README.md` references it. | If dropped: `git rm`, remove the `!benchmarks/results/benchmark_report.xlsx` line from `.gitignore`, and reword `benchmarks/README.md` §"results". |

## 3. Local-only clutter (not in git)

| Path | Issue | Status |
|------|-------|--------|
| `.pytest_tmp_all_changes/`, `.pytest_tmp_bench/`, `.pytest_tmp_codex/`, `.pytest_tmp_commit/`, `.pytest_tmp_current/`, `.pytest_tmp_harness/` | Leftover test temp dirs at the repo root with broken ACLs — even `git status` prints "Permission denied" warnings for them. Deletion failed from a normal shell (`Remove-Item`, `takeown`, `icacls` all denied). | I added `.pytest_tmp_*/` to `.gitignore` so git skips them. To actually delete them, run from an **elevated** PowerShell: `takeown /f .pytest_tmp_bench /r /d y; icacls .pytest_tmp_bench /reset /t; Remove-Item -Recurse -Force .pytest_tmp_bench` (repeat per dir), or delete via Explorer as admin. |

## Explicitly checked and kept (not clutter)

- `glm_possibility_eval/` — added in the commits just pulled; active decision-support eval, not a leftover.
- `PAIN_POINTS.md` — recent, self-contained analysis doc; actively referenced thinking for the paper.
- `references/EXTERNAL_REPOS.md`, `references/EXTRACTION_LOG.md` — provenance documentation for reverse-engineered ideas; referenced by `PAIN_POINTS.md` and the handoff doc; legally/academically valuable.
- `scripts/*.py`, `ci2lab/security/*`, `audit/redteam*` — all wired into tests, docs, or CI-adjacent tooling; none are one-time personal scripts.
- `docs/CLAUDE_EXPERIMENTAL_VALIDATION.md` — records a finished validation **and** how to reproduce it; the reproduction instructions keep it useful.
- Façade modules with re-export-only imports (`ci2lab/harness/loop.py`, `permissions.py`, …) — protected by CLAUDE.md convention; not dead code.
- `HARNESS_COMPARISON.md` (untracked, repo root) — kept untouched per prior decision.
