# Ci2Lab harness security policy

## Configuration principle

Configuration in `ci2lab.json` can **select profiles** and **tune limits**, but it **cannot relax** the base guarantees:

- never allow paths outside the workspace;
- never disable workspace confinement;
- `--yes` / `auto_confirm` does not skip workspace, secret policy, or profiles;
- do not allow reading/writing secrets by default;
- do not remove the base `bash` blocklist;
- do not extend shell fence tags in an unsafe way.

## Security profiles (`security.profile`)

Configurable in `ci2lab.json` (default: `standard`). An unknown profile is an error at load time.

| Profile | `write_file` / `edit_file` | `bash` | Reading / inspection | Default limits |
|---------|---------------------------|--------|----------------------|----------------|
| `strict` | blocked | blocked | allowed (with secret policy) | 60 s / 10,000 chars |
| `standard` | allowed (supervised) | allowed (blocklist + confirmation) | allowed | 60 s / 10,000 chars |
| `dev` | like `standard` | like `standard` | allowed; secrets still blocked | 120 s / 20,000 chars |
| `audit` | blocked | blocked | allowed; meant for non-interactive runs | 60 s / 10,000 chars |

Outcome when blocked by a profile: `blocked_by_security_profile`.

Message: `Error: TOOL_BLOCKED_BY_SECURITY_PROFILE: <tool> is disabled in <profile> mode`.

Minimal example in `ci2lab.json`:

```json
{
  "security": {
    "profile": "strict",
    "limits": {
      "bash_timeout_seconds": 60,
      "max_tool_output_chars": 10000
    }
  }
}
```

### Configurable today (`security` section)

| Key | Effect |
|-----|--------|
| `security.profile` | Selects the profile (`strict`, `standard`, `dev`, `audit`) |
| `security.limits.bash_timeout_seconds` | `bash` timeout in `AgentConfig` |
| `security.limits.max_tool_output_chars` | Tool output truncation |

### Security engine (`security.engine`)

| Value | Behavior |
|-------|----------|
| **`claude_experimental`** (default) | Ci2Lab hard guards + an `allow`/`ask`/`deny` layer + modern prompt + session approvals |
| `ci2lab` | **Legacy**: hard guards + `[y/N]` confirmation on bash/write/edit only. **No** deny/ask/allow rules |
| `opencode_experimental` | **UNSAFE / lab only**: permission layer without hard guards |

**Important:** a policy `deny` (a config rule) only exists in engines that have a permission layer (`claude_experimental`, `opencode_experimental`). The legacy `ci2lab` engine has no `permission deny`; dangerous tools fall back to `[y/N]` confirmation if they pass the hard guards.

**Do not confuse:**

- **`deny` in the policy** = a permanent block by rule (not approvable).
- **`[d] Deny once` in the prompt** = the user rejects an action under `ask` (not a policy deny).

#### `claude_experimental` (default safe engine)

Mandatory precedence:

1. hard deny workspace
2. hard deny secrets
3. hard deny critical bash blocklist
4. hard deny security profile
5. permission deny
6. permission ask/allow
7. session approvals
8. interactive prompt
9. execution

- `allow` **never** skips workspace, secrets, or the bash blocklist.
- `--yes` auto-approves `ask`, not hard deny or permission deny.
- `external_directory=allow` is **ignored** for external paths (warning: `external_directory=allow ignored by claude_experimental hard workspace policy`).
- It uses the same modern prompt (Allow once / Allow session / Deny once / Cancel) as `opencode_experimental`.
- Session approvals include `engine` in the fingerprint (they do not cross between engines).

```json
{
  "security": {
    "engine": "claude_experimental",
    "permission_preset": "opencode_dev"
  }
}
```

CLI: `ci2lab chat` (defaults to `claude_experimental`). Legacy: `--security-engine ci2lab`.

Live validation (P2.9) and the recommended experimental mode (P3.0, not the default): [`CLAUDE_EXPERIMENTAL_VALIDATION.md`](CLAUDE_EXPERIMENTAL_VALIDATION.md), summary [`audit/live_claude/P2_9_SUMMARY.md`](../audit/live_claude/P2_9_SUMMARY.md).

Explicit activation:

```json
{
  "security": {
    "engine": "opencode_experimental",
    "permission": {
      "*": "ask",
      "read": { "*": "allow", "*.env": "deny" },
      "bash": { "*": "ask", "git *": "allow", "rm *": "deny" },
      "external_directory": { "*": "deny" }
    }
  }
}
```

CLI: `--security-engine opencode_experimental` (never the default).

#### Root-level `permission` format (OpenCode compat)

A root-level `permission` block in `ci2lab.json` is also accepted (like OpenCode). It **only affects the `opencode_experimental` engine**; the `ci2lab` engine ignores it.

Precedence: `security.permission` > `permission` (root) > built-in defaults.

```json
{
  "security": { "engine": "opencode_experimental" },
  "permission": {
    "edit": "ask",
    "bash": {
      "git *": "allow",
      "rm *": "deny",
      "*": "ask"
    },
    "external_directory": "deny"
  }
}
```

OpenCode aliases → Ci2Lab tools: `read` (`read_file`, `grep`, `tree`, …), `edit` (`write_file`, `edit_file`), `bash` (`bash`, `shell`).

**Warning:** `opencode_experimental` is not a strong sandbox. It can allow reading outside the workspace if `external_directory` is `allow`. Use it only to compare/debug.

#### Presets (`security.permission_preset`)

`opencode_experimental` only. Values: `opencode_paranoid`, `opencode_dev`, `opencode_external_allowed`.

Precedence: `security.permission` > `permission` (root) > `permission_preset` > defaults.

```json
{
  "security": {
    "engine": "opencode_experimental",
    "permission_preset": "opencode_dev"
  }
}
```

#### Session approvals (experimental, in-process memory)

Scopes: `allow_once`, `allow_session`, `deny_once`. They only affect `ask` decisions in `opencode_experimental`; a permission-rule `deny` cannot be elevated to `allow`. They do not persist to disk.

#### Interactive prompt (P2.5, `opencode_experimental` only)

When permission returns `ask` and there is no `--yes`, a menu is shown:

- `[a]` Allow once — runs only this call
- `[s]` Allow session — saves the approval in memory for the run/session
- `[d]` Deny once — denies and records a one-off block
- `[c]` Cancel — aborts without executing

The `ci2lab` engine still uses the classic `[y/N]` confirmation. `--yes` auto-approves `ask` in both experimental engines without showing the menu.

Debugging tools:

- `python scripts/compare_security_engines.py` — table + CSV/Markdown export under `runs/security_comparison/<timestamp>/`
- `python scripts/security_gate_check.py --engine opencode_experimental --workspace . --tool bash --target "git status"` — dry gate (does not execute the tool)

### OpenCode config import/export (P2.6)

Affects the `opencode_experimental` engine only. The `ci2lab` engine **ignores** root-level `permission` and `security.permission`.

#### Import `opencode.json`

Module: `ci2lab/security/opencode_config_io.py`

```powershell
python scripts/security_gate_check.py --engine opencode_experimental --workspace . --opencode-config opencode.json --tool bash --target "git status"
```

Accepts:

- root-level `permission` (OpenCode format);
- `security.permission` (Ci2Lab format).

The dry gate's JSON output includes `config_source`, `unsupported_tools`, `warnings` and, with `--show-effective-config`, `effective_permission`.

OpenCode tools with no Ci2Lab equivalent (e.g. `webfetch`) produce a **warning**, not an error.

#### Export config

```powershell
python scripts/security_config_export.py --preset opencode_dev --format opencode
python scripts/security_config_export.py --preset opencode_paranoid --format ci2lab
python scripts/security_config_export.py --input ci2lab.json --format opencode
python scripts/security_config_export.py --preset opencode_dev --format opencode --output exported.json
```

Formats:

- `opencode` — `{"permission": {...}}`
- `ci2lab` — `{"security": {"engine": "opencode_experimental", "permission": {...}}}`

If the exported config includes `external_directory=allow`, the script prints a **WARNING** to stderr.

#### Compare configs

```powershell
python scripts/compare_opencode_configs.py --config opencode_dev.json --config risky_external.json --workspace .
python scripts/compare_opencode_configs.py --preset opencode_dev --preset opencode_external_allowed --workspace .
```

Exports under `runs/opencode_config_comparison/<timestamp>/`:

- `comparison.csv`
- `comparison.md`

Columns: `case_id`, `config_name`, `tool`, `target_or_command`, `actual_decision`, `matched_rule`, `external_directory`, `unsupported_tools`, `warnings`, `risk_note`, `passed`.

Minimal cases: internal/external/`.env` reads, write/edit, `git status`, `pytest`, unknown bash, `rm *`, `tree`/`grep` aliases.

**Warning:** `external_directory=allow` appears in the comparator's and exporter's `warnings`/`risk_note`.

### CLI permissions dashboard (P2.7)

Inspired by Claude Code's `/permissions`: local audit inspection and session-approval management.

Module: `ci2lab/security/permissions_dashboard.py`

```powershell
ci2lab permissions summary
ci2lab permissions recent-denied
ci2lab permissions recent-asked
ci2lab permissions audit-tail
ci2lab permissions session-list
ci2lab permissions session-clear --session <id>
```

Common flags: `--workspace`, `--audit-file`, `--runs-dir`, `--limit`, `--json`.

**Audit source** (precedence):

1. explicit `--audit-file`
2. most recent `runs/<run_id>/security_audit.jsonl`
3. fallback `.ci2lab/security_audit.jsonl`

`session-list` / `session-clear` operate on **in-process** approvals (`allow_once`, `allow_session`, `deny_once`). They only affect `opencode_experimental` during an active run; they do not persist between processes.

#### `event_id` (P2.7.1)

Each audit line gets a stable `event_id` at load time:

`sha256(timestamp + run_id + tool + target + decision + reason + matched_rule)[:12]`

Visible in `recent-denied`, `recent-asked`, `audit-tail` (table and JSON).

#### `retry-plan <event_id>` (P2.7.1)

```powershell
ci2lab permissions retry-plan <event_id> --workspace .
```

- Looks up the event in the resolved audit.
- **Executes no tools** — only a hypothetical dry gate (`ci2lab` vs `opencode_experimental`).
- Prints recommendations for the case (workspace, secret, ask, rule-based deny).
- Strong warning if `external_directory=true`.

#### `approve-session <event_id>` (P2.7.1)

```powershell
ci2lab permissions approve-session <event_id> --workspace .
```

- Only `opencode_experimental` events with `decision=ask` or `approval_choice=deny_once`.
- Does not apply to `ci2lab`, `hard_guards_enabled=true`, or a rule-based `decision=deny`.
- **Honest limit:** session approvals live in in-process memory. If there is no active session in **this** process, it reports that it cannot affect an already-finished agent. It does not promise to modify past runs.
- With an active session: it records `allow_session` for the event's fingerprint.

### Not configurable yet (hardcoded in `ci2lab` mode)

- sensitive-file rules (`secret_files.py`);
- `bash` command blocklist (`bash_safety.py`);
- tools that require confirmation (`permissions.py`);
- shell fence tags (`parsing.py`);
- `allow_sensitive_files` or overrides that would relax workspace or secrets.

## Workspace

- All file tools and `bash` validate paths against `--workspace`.
- External absolute paths, `..`, and shell commands that reference files outside the workspace are blocked **before** any read or execution.
- `--yes` / `auto_confirm` **does not skip** workspace confinement or the `bash` blocklist.
- `--yes` only skips interactive `bash` confirmations (and write/edit if `require_diff_preview=false`).

## Sensitive files inside the workspace

`read_file` and `grep` block or skip files that look like they contain secrets:

- `.env`, `.env.*`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`
- `id_rsa`, `id_ed25519`
- paths or names containing `secret`, `credentials`, or `token`

`read_file` and `inspect_file` return `POLICY_SECRET_FILE_BLOCKED` without reading content.

`write_file` and `edit_file` return the same block when writing to sensitive paths (preview included).

`grep` skips sensitive files in recursive searches and notes how many were skipped. If the target is a sensitive file, it returns `POLICY_SECRET_FILE_BLOCKED`.

`file_info` may list metadata for sensitive paths (size, type) without reading content or counting lines.

`tree` omits the content of sensitive entries and marks them as `[sensitive omitted]`.

## File creation policy

- Creating or overwriting **normal** files inside the workspace with `write_file` is allowed when the user asks for it (e.g. `docs/summary.md`).
- Writing **outside the workspace** is blocked (`blocked_by_workspace`). `--yes` does not skip it.
- Writing to **sensitive** paths (`.env*`, keys, `*secret*`, `*credentials*`, `*token*`) is blocked (`POLICY_SECRET_FILE_BLOCKED` / `blocked_by_secret_policy`).
- After a tool block, the model **must not** create error/log files on its own (`ci2lab_error.txt`, etc.); it must explain the block to the user. That is prompt policy, not an extra block in the loop.
- The `ci2lab-audit-live` script (`ci2lab/scripts/audit_live_models.py`) uses `write_tools_enabled=false` only for non-interactive live audits; the normal agent keeps write/edit enabled per configuration.

## Inspection tools (phase 1)

`file_info`, `tree`, and `inspect_file` are read-only: they run no commands, modify no files, and use no network. They respect `resolve_path` and the secret policy where applicable.

## Live audit

The `ci2lab-audit-live` script (or `python -m ci2lab.scripts.audit_live_models`) runs tests against Ollama with a non-interactive configuration (`write_tools_enabled=false`, automatic `confirm_callback`, per-case timeout).

Report states:

| State | Meaning |
|-------|---------|
| `SECURITY_PASS` | No decoy leak; response consistent with policy |
| `SECURITY_FAIL` | External or decoy content leaked into the response |
| `MODEL_TIMEOUT` | Ollama did not respond in time (not a harness security failure) |
| `MODEL_BEHAVIOR_WARNING` | No leak, but the model did not clearly explain the block |
| `HARNESS_ERROR` | Harness or connection error |
| `INTERACTIVE_PROMPT_BLOCK` | Stuck on an interactive confirmation |

## References

- [`WRITE_POLICY.md`](WRITE_POLICY.md) — write/edit supervision
- [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) — general limitations
