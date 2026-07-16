"""Functional-correctness oracle for benchmark runs.

Grading is exit-code / exact-match based (no LLM judge), so it is agent-agnostic
and reproducible. A run is *solved* only when every configured check passes:

- ``answer_contains`` — required substrings in the agent's final answer.
- ``command`` / ``fail_to_pass`` / ``pass_to_pass`` — shell commands run in the
  workspace after the agent finishes (hidden oracle tests injected first).
- ``forbid_paths`` — files the agent must not have modified (checked via git).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ci2lab.bench.task import BenchTask

__all__ = ["CheckResult", "Verdict", "verify"]

_TIMEOUT_EXIT = 124
_NOT_FOUND_EXIT = 127


@dataclass
class CheckResult:
    """Outcome of a single grading check."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class Verdict:
    """Aggregated grading outcome for one run."""

    solved: bool
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failure_reasons(self) -> list[str]:
        """One ``name: detail`` string per failed check."""
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]


def verify(
    task: BenchTask,
    *,
    workspace: Path,
    final_answer: str,
    changed_paths: list[str] | None = None,
) -> Verdict:
    """Grade one run against a task's :class:`~ci2lab.bench.task.VerifierSpec`.

    Args:
        task: The task being graded.
        workspace: The workspace directory after the agent ran and the hidden
            oracle files were injected.
        final_answer: The agent's final textual answer.
        changed_paths: Workspace paths the agent modified (for ``forbid_paths``);
            typically captured before the hidden oracle files were injected.

    Returns:
        A :class:`Verdict`; ``solved`` is true only when every check passed.
    """
    spec = task.verifier
    checks: list[CheckResult] = []

    if not spec.has_oracle:
        checks.append(CheckResult("config", False, "task defines no oracle (answer/command/tests)"))
        return Verdict(solved=False, checks=checks)

    checks.extend(_check_forbidden(spec.forbid_paths, changed_paths or []))
    checks.extend(_check_answer(spec.answer_contains, spec.answer_contains_ordered, final_answer))
    checks.extend(_check_commands(task, workspace))

    return Verdict(solved=all(c.passed for c in checks), checks=checks)


def _check_forbidden(forbid_paths: list[str], changed: list[str]) -> list[CheckResult]:
    """Fail if any modified path falls under a forbidden prefix."""
    results: list[CheckResult] = []
    for forbidden in forbid_paths:
        prefix = forbidden.rstrip("/")
        hit = next(
            (p for p in changed if p == prefix or p.startswith(prefix + "/")),
            None,
        )
        results.append(
            CheckResult(
                f"forbid:{forbidden}",
                hit is None,
                "not modified" if hit is None else f"forbidden path modified: {hit}",
            )
        )
    return results


def _check_answer(needles: list[str], ordered: bool, answer: str) -> list[CheckResult]:
    """Check that the final answer contains the required substrings."""
    if not needles:
        return []
    lowered = answer.lower()
    if ordered:
        ok = _ordered_contains(lowered, [n.lower() for n in needles])
        return [
            CheckResult(
                "answer_contains_ordered",
                ok,
                "found in order" if ok else f"{needles} not all present in order",
            )
        ]
    results: list[CheckResult] = []
    for needle in needles:
        ok = needle.lower() in lowered
        results.append(
            CheckResult(
                f"answer:{needle}",
                ok,
                "found" if ok else f"{needle!r} not in final answer",
            )
        )
    return results


def _check_commands(task: BenchTask, workspace: Path) -> list[CheckResult]:
    """Run the configured command / FAIL_TO_PASS / PASS_TO_PASS checks."""
    spec = task.verifier
    results: list[CheckResult] = []

    if spec.command is not None:
        code, out = _run_command(spec.command, workspace, spec.timeout_seconds)
        ok = code == spec.expect_exit
        results.append(
            CheckResult(
                "command",
                ok,
                f"exit {code} (expected {spec.expect_exit})" + _tail(out, ok),
            )
        )

    for label, commands in (
        ("fail_to_pass", spec.fail_to_pass),
        ("pass_to_pass", spec.pass_to_pass),
    ):
        for cmd in commands:
            code, out = _run_command(cmd, workspace, spec.timeout_seconds)
            ok = code == 0
            results.append(
                CheckResult(
                    f"{label}:{cmd}",
                    ok,
                    "passed" if ok else f"exit {code}" + _tail(out, ok),
                )
            )
    return results


def _run_command(cmd: str, workspace: Path, timeout: int) -> tuple[int, str]:
    """Run ``cmd`` in ``workspace`` and return ``(exit_code, combined_output)``.

    ``PYTHONPATH`` is prefixed with the workspace so test files can import
    modules created directly in the workspace root. A timeout yields exit
    ``124``; a missing executable yields ``127``.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(workspace) + (os.pathsep + existing if existing else "")
    try:
        proc = subprocess.run(
            _command_argv(cmd),
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return _TIMEOUT_EXIT, "timeout"
    except OSError as exc:
        return _NOT_FOUND_EXIT, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _command_argv(cmd: str) -> list[str]:
    """Split a verifier command, pinning bare Python calls to this interpreter."""
    argv = shlex.split(cmd)
    if argv and argv[0].lower() in {"python", "python.exe", "python3", "python3.exe"}:
        argv[0] = sys.executable
    return argv


def _ordered_contains(haystack: str, needles: list[str]) -> bool:
    """Whether all ``needles`` appear in ``haystack`` in the given order."""
    pos = 0
    for needle in needles:
        idx = haystack.find(needle, pos)
        if idx < 0:
            return False
        pos = idx + len(needle)
    return True


def _tail(output: str, ok: bool, limit: int = 300) -> str:
    """Append a short tail of command output to a failure detail."""
    if ok or not output:
        return ""
    snippet = output.strip()[-limit:]
    return f" — {snippet}"
