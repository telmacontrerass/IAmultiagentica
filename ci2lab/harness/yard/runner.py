"""Execute a Yard component entrypoint, with readiness and dependency gating.

Execution is deliberately defensive: the salvaged modules are unvetted
third-party code, several were sanitised (redacted prompts/schemas, elided
constants), and some reach the network or the host. :func:`execute` therefore
runs a series of gates before importing anything, and only imports and calls the
target function once every gate passes. Every path returns a plain result
dictionary (never raises) so the gateway tool can serialise it directly.

Security: execution is in-process but governed by the run's security policy, the
same one the built-in tools obey.

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

import importlib
import importlib.util
import io
import sys
from collections.abc import Iterable
from contextlib import redirect_stdout
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


def _jsonable(value: Any) -> Any:
    """Coerce ``value`` into something JSON-serialisable.

    Dicts and lists are converted recursively; scalars pass through; anything
    else falls back to its ``repr`` so a result is always representable.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    return repr(value)


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


def _load_callable(entrypoint: YardEntrypoint, core_dirs: Iterable[Path]) -> Any:
    """Import ``entrypoint.module`` off the Yard core dirs and return the target.

    All component ``core/`` directories are placed on ``sys.path`` for the
    duration of the import so cross-component imports (e.g. the Places client
    importing ``geometria``) resolve. ``sys.path`` is restored afterwards.

    Raises:
        ImportError: The module could not be imported.
        AttributeError: The module has no such function.
    """
    added = [str(Path(d).resolve()) for d in core_dirs]
    saved = list(sys.path)
    sys.path[:0] = added
    try:
        importlib.invalidate_caches()
        module = importlib.import_module(entrypoint.module)
        module = importlib.reload(module)
        return getattr(module, entrypoint.function)
    finally:
        sys.path[:] = saved


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

    try:
        func = _load_callable(entrypoint, core_dirs)
    except (ImportError, AttributeError) as exc:
        return {
            **base,
            "ok": False,
            "status": "import_error",
            "message": f"Could not load `{entrypoint.module}.{entrypoint.function}`: {exc}",
        }

    stdout = io.StringIO()
    try:
        with redirect_stdout(stdout):
            result = func(**args)
    except Exception as exc:  # salvaged code may raise anything; never propagate
        return {
            **base,
            "ok": False,
            "status": "runtime_error",
            "message": f"{type(exc).__name__}: {exc}",
        }

    # Hand back the whole result; the executor's central offload path preserves
    # and previews it when it exceeds max_tool_output_chars.
    out: dict[str, Any] = {**base, "ok": True, "status": "ok", "result": _jsonable(result)}
    captured = stdout.getvalue().strip()
    if captured:
        out["stdout"] = captured[:2000]
    return out
