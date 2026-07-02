"""Execute a Yard component entrypoint, with readiness and dependency gating.

Execution is deliberately defensive: the salvaged modules are unvetted
third-party code, several were sanitised (redacted prompts/schemas, elided
constants), and some reach the network or the host. :func:`execute` therefore
runs a series of gates *in the harness process* before touching the code, and
only once every gate passes does it hand the call to a short-lived, isolated
child process (:mod:`ci2lab.harness.yard._worker`). Every path returns a plain
result dictionary (never raises) so the gateway tool can serialise it directly.

Security: the salvaged code never runs in the harness process. It executes in a
separate Python process with a kill-timeout, so a crash, hang, or resource leak
in a component cannot take down or corrupt the agent, and no module-level state
leaks between runs. On top of that isolation the run's security policy — the same
one the built-in tools obey — is enforced *before* the worker is spawned:

- A host-mutating (``side_effect``) entrypoint is blocked outright under a
  profile that disables ``bash``/``write_file`` (``strict``/``audit``); otherwise
  it is routed through the harness confirmation channel (auto-confirm or the
  configured ``confirm_callback``) and refused when write tools are disabled.
- Every parameter an entrypoint declares as a filesystem path is confined to the
  workspace before the call, mirroring the read/write file tools' jail.

Successful results are handed back whole; the executor's central output-offload
path (keyed on ``max_tool_output_chars``) preserves and previews large returns,
so the runner does not truncate them itself.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ci2lab.harness.security_profiles import (
    SECURITY_PROFILE_BLOCKED_OUTCOME,
    is_tool_blocked_by_profile,
)
from ci2lab.harness.yard.loader import YardComponent, YardEntrypoint
from ci2lab.security.paths import PathViolationError, resolve_workspace_path

if TYPE_CHECKING:
    from ci2lab.harness.types import AgentConfig

#: Path to the out-of-process execution worker spawned for every ``run``.
_WORKER = Path(__file__).resolve().parent / "_worker.py"

#: Fallback kill-timeout (seconds) when the config supplies none.
_DEFAULT_TIMEOUT_SECONDS = 60


def _missing_dependencies(requires: Iterable[str]) -> list[str]:
    """Return the subset of ``requires`` that cannot be imported."""
    missing: list[str] = []
    for dep in requires:
        try:
            found = importlib.util.find_spec(dep) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(dep)
    return missing


def _host_mutation_approved(
    component: YardComponent,
    entrypoint: YardEntrypoint,
    config: AgentConfig,
) -> bool:
    """Decide whether a host-mutating entrypoint may run, via the harness.

    Mirrors how the write tools gate: an auto-confirmed run proceeds; otherwise
    the configured confirm callback decides; with neither, the safe default is to
    decline — never auto-run host mutation, and never block on interactive input
    inside a headless run.

    Args:
        component: The component owning the entrypoint (named in the prompt).
        entrypoint: The host-mutating entrypoint awaiting approval.
        config: Active run configuration supplying the confirmation channel.

    Returns:
        ``True`` when the run is approved to proceed, ``False`` otherwise.
    """
    if config.auto_confirm:
        return True
    callback = config.confirm_callback
    if callback is None:
        return False
    detail = (
        f"Yard component `{component.name}` entrypoint `{entrypoint.function}` (mutates the host)"
    )
    try:
        return bool(callback(f"yard/{component.name}", detail))
    except Exception:
        return False


def _run_isolated(
    entrypoint: YardEntrypoint,
    args: dict[str, Any],
    core_dirs: Iterable[Path],
    *,
    timeout: int,
) -> dict[str, Any]:
    """Execute one entrypoint in a short-lived isolated worker process.

    The component ``core/`` directories are passed to the worker so cross-component
    imports (e.g. the Places client importing ``geometria``) resolve there. The
    child is killed if it runs longer than ``timeout`` seconds.

    Args:
        entrypoint: The entrypoint to execute.
        args: Validated call arguments (already gated in the parent).
        core_dirs: Every loaded component's ``core/`` directory.
        timeout: Wall-clock kill-timeout for the child, in seconds.

    Returns:
        A partial result dict: ``{"ok": True, "result": ..., "stdout"?: ...}`` on
        success, or ``{"ok": False, "status": ..., "message": ...}`` describing a
        component error, timeout, crash, or unparseable output.
    """
    payload = json.dumps(
        {
            "core_dirs": [str(Path(d).resolve()) for d in core_dirs],
            "module": entrypoint.module,
            "function": entrypoint.function,
            "args": args,
        }
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(_WORKER)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "runtime_error",
            "message": f"Component timed out after {timeout}s and was terminated.",
        }
    except OSError as exc:  # could not spawn the interpreter
        return {
            "ok": False,
            "status": "runtime_error",
            "message": f"Could not start isolated worker: {exc}",
        }

    envelope = _parse_worker_output(proc.stdout)
    if envelope is None:
        detail = (proc.stderr or "").strip()[:500]
        return {
            "ok": False,
            "status": "runtime_error",
            "message": (
                f"Isolated worker returned no parseable result (exit {proc.returncode}). {detail}"
            ).strip(),
        }

    if envelope.get("ok"):
        out: dict[str, Any] = {"ok": True, "result": envelope.get("result")}
        stdout = str(envelope.get("stdout") or "")
        if stdout:
            out["stdout"] = stdout[:2000]
        return out

    error_type = str(envelope.get("error_type", ""))
    status = (
        "import_error"
        if error_type in {"ImportError", "ModuleNotFoundError", "AttributeError"}
        else "runtime_error"
    )
    return {
        "ok": False,
        "status": status,
        "message": str(envelope.get("error") or "unknown error"),
    }


def _parse_worker_output(stdout: str) -> dict[str, Any] | None:
    """Parse the worker's JSON envelope from its stdout; ``None`` if unparseable."""
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text.splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return parsed if isinstance(parsed, dict) else None


def execute(
    component: YardComponent,
    entrypoint: YardEntrypoint,
    args: dict[str, Any],
    core_dirs: Iterable[Path],
    *,
    config: AgentConfig,
) -> dict[str, Any]:
    """Run one entrypoint, gating on readiness, permission and dependencies.

    Args:
        component: The component the entrypoint belongs to.
        entrypoint: The entrypoint to execute.
        args: Caller-supplied arguments forwarded to the callable.
        core_dirs: The ``core/`` directories of all loaded components, added to
            ``sys.path`` so cross-component imports resolve.
        config: Active run configuration; supplies the write-tools flag and the
            confirmation channel used to gate host-mutating entrypoints.

    Returns:
        A result dictionary with ``ok`` (bool), ``status`` (a short machine
        code) and either ``result`` on success or ``message`` plus context on a
        declined or failed run. The function never raises.
    """
    base = {
        "component": component.name,
        "entrypoint": entrypoint.function,
    }
    args = dict(args or {})
    # `confirm` is no longer a caller-set unlock: approval comes from the harness
    # confirmation channel. Strip any stray value so it is never passed as a kwarg.
    args.pop("confirm", None)

    # Integrity gate: a component whose vendored code no longer matches its
    # recorded core_sha256 has drifted or been tampered with — refuse outright,
    # before any other consideration.
    if not component.verified:
        return {
            **base,
            "ok": False,
            "status": "signature_mismatch",
            "message": (
                "This component's core code does not match its recorded "
                "`core_sha256` signature (drift or tampering); execution refused. "
                "Regenerate the signature if the change was intentional."
            ),
        }

    # A redacted entrypoint can never run correctly, regardless of environment,
    # so report that first — it is the most actionable message.
    if entrypoint.ready == "needs_config":
        return {
            **base,
            "ok": False,
            "status": "needs_config",
            "message": (
                entrypoint.note
                or "This entrypoint's salvaged source has redacted prompts/schemas "
                "and cannot run as-is."
            ),
            "porting_guide": "Use `yard describe` and adapt per the porting guide.",
        }

    if entrypoint.ready == "side_effect":
        if is_tool_blocked_by_profile(config.security_profile, "bash"):
            return {
                **base,
                "ok": False,
                "status": SECURITY_PROFILE_BLOCKED_OUTCOME,
                "message": (
                    "Host-mutating Yard entrypoints are disabled under the "
                    f"`{config.security_profile}` security profile "
                    "(which also blocks bash/write_file)."
                ),
            }
        if not config.write_tools_enabled:
            return {
                **base,
                "ok": False,
                "status": "blocked_read_only",
                "message": (
                    "Write tools are disabled for this run, so this host-mutating "
                    "entrypoint will not execute."
                ),
            }
        if not _host_mutation_approved(component, entrypoint, config):
            return {
                **base,
                "ok": False,
                "status": "needs_confirm",
                "message": (
                    entrypoint.note
                    or "This entrypoint changes the host (opens windows/spawns processes)."
                )
                + " It requires run confirmation (auto_confirm or an approving "
                "confirm callback), which was not granted.",
            }

    if entrypoint.ready == "needs_key":
        missing_keys = [k for k in entrypoint.secret_params if not args.get(k)]
        if missing_keys:
            return {
                **base,
                "ok": False,
                "status": "needs_key",
                "message": (
                    "This entrypoint calls an external API. Provide: " + ", ".join(missing_keys)
                ),
                "missing": missing_keys,
            }

    # Environment gate: a missing pip dependency blocks import. Checked after the
    # caller-owned gates (key/confirm) so those more actionable messages win when
    # several are unmet at once.
    missing_deps = _missing_dependencies(entrypoint.requires)
    if missing_deps:
        return {
            **base,
            "ok": False,
            "status": "needs_dependency",
            "message": (
                "Missing Python dependency for this entrypoint: "
                + ", ".join(missing_deps)
                + f". Install with `pip install {' '.join(missing_deps)}`."
            ),
            "missing": missing_deps,
        }

    missing_params = [p for p in entrypoint.required_params if p not in args]
    if missing_params:
        return {
            **base,
            "ok": False,
            "status": "missing_params",
            "message": "Missing required parameter(s): " + ", ".join(missing_params),
            "missing": missing_params,
        }

    # Workspace confinement: any path-typed argument must resolve inside the
    # workspace, mirroring the read/write file tools' jail.
    for name in entrypoint.path_params:
        value = args.get(name)
        if value in (None, ""):
            continue
        try:
            resolve_workspace_path(config.cwd, str(value))
        except PathViolationError as exc:
            return {
                **base,
                "ok": False,
                "status": "blocked_by_workspace",
                "message": f"Path argument `{name}` escapes the workspace: {exc}",
            }

    # Hand the actual call to an isolated child process. All gates above have
    # already passed, so only the (untrusted) execution itself is offloaded.
    outcome = _run_isolated(
        entrypoint,
        args,
        core_dirs,
        timeout=config.bash_timeout_seconds or _DEFAULT_TIMEOUT_SECONDS,
    )
    if not outcome["ok"]:
        return {**base, **outcome}

    # Hand back the whole result; the executor's central offload path preserves
    # and previews it when it exceeds max_tool_output_chars.
    out: dict[str, Any] = {**base, "ok": True, "status": "ok", "result": outcome["result"]}
    if outcome.get("stdout"):
        out["stdout"] = outcome["stdout"]
    return out
