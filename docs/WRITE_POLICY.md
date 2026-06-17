# Supervised editing policy

## Status

`write_file` and `edit_file` are **enabled and validated**, but only in **supervised mode**.

They are not the agent's primary flow over the repository code, and they are not autonomous editing: every on-disk change requires explicit user review and approval when `require_diff_preview=true` (the default).

## What supervised mode means

- A diff preview is always generated when `require_diff_preview=true`.
- The user must visually approve the diff (legacy engine: `[y/N]`; `claude_experimental`: the Allow/Deny prompt).
- `--yes` **does not skip** the preview when `require_diff_preview=true`.
- Changes are recorded under `runs/` (`tool_calls.jsonl` with an `outcome`).
- They can be disabled entirely with `write_tools_enabled=false`.

Technical detail of the flow: [`docs/audits/write_edit_tools_status.md`](audits/write_edit_tools_status.md).

## Recommended use today

- Temporary files and test workspaces.
- Test configs or local fixtures.
- Small, contained changes.
- Evals (`005`, `006`, `007`) and harness validation.
- Controlled prototypes outside critical product code.

## Not recommended yet

- Mass editing of real repo code as the agent's primary flow.
- Large refactors without line-by-line human review.
- Critical production changes, or sensitive paths, without reviewing the diff.
- Automated scripts with `require_diff_preview=false` (this bypasses the supervision barrier).

## Pending before intensive editing

- Git snapshot / rollback before applying changes.
- More editing evals over real code.
- A better per-file-type policy (path allowlist/denylist).
- A possible additional dry-run mode.

## References

- [Technical write/edit status](audits/write_edit_tools_status.md)
- [Validation in mock/live evals](audits/live_eval_status.md) — tasks `005`–`007`
- [Known limitations](KNOWN_LIMITATIONS.md)
