"""Out-of-process executor for a single Yard entrypoint.

Runs in a short-lived child process spawned by :mod:`ci2lab.harness.yard.runner`.
It reads one JSON job from stdin, imports the requested vendored ``core`` module
with the component directories on ``sys.path``, calls the target function, and
writes a single JSON result envelope to stdout.

The script is intentionally dependency-free — standard library plus the vendored
module it loads — so the unvetted salvaged code executes in isolation from the
harness process. All parent-side gating (readiness, security profile, confirm,
dependencies, parameters, path confinement) has already run before this worker
is spawned; the worker's job is purely to execute and report.

Job (stdin, JSON): ``{"core_dirs": [...], "module": str, "function": str,
"args": {...}}``. Envelope (stdout, JSON): ``{"ok": true, "result": ...,
"stdout": str}`` on success, or ``{"ok": false, "error_type": str,
"error": str}`` on any failure. The worker never raises past ``main``; every
outcome is reported as an envelope.
"""

from __future__ import annotations

import importlib
import io
import json
import sys
from contextlib import redirect_stdout
from typing import Any

# Captured before anything can redirect it, so the result envelope always
# reaches the real stdout even if the component leaves stdout hooked.
_STDOUT = sys.stdout


def _jsonable(value: Any) -> Any:
    """Coerce ``value`` into something JSON-serialisable (repr as last resort)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    return repr(value)


def _emit(envelope: dict[str, Any]) -> None:
    """Write the result envelope as a single JSON document to the real stdout."""
    _STDOUT.write(json.dumps(envelope, ensure_ascii=False))
    _STDOUT.flush()


def main() -> int:
    """Read the job from stdin, execute one entrypoint, emit the envelope."""
    try:
        job = json.loads(sys.stdin.read())
    except ValueError as exc:
        _emit({"ok": False, "error_type": "ValueError", "error": f"invalid job: {exc}"})
        return 0

    for core_dir in job.get("core_dirs", []):
        if core_dir not in sys.path:
            sys.path.insert(0, core_dir)

    module_name = str(job.get("module", ""))
    function_name = str(job.get("function", ""))
    args = job.get("args") or {}

    captured = io.StringIO()
    try:
        with redirect_stdout(captured):
            module = importlib.import_module(module_name)
            func = getattr(module, function_name)
            result = func(**args)
    except Exception as exc:  # report any failure of the salvaged code as data
        _emit(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return 0

    _emit({"ok": True, "result": _jsonable(result), "stdout": captured.getvalue().strip()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
