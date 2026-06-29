"""Benchmark task definitions (:class:`BenchTask`) and their loaders.

A ``BenchTask`` is the benchmark-suite analogue of ``ci2lab.evals.task.EvalTask``
but deliberately separate (benchmarks are not tests). Each task bundles the
agent-visible prompt and fixtures, the hidden oracle files injected only at
grading time, and a :class:`VerifierSpec` describing how a run is graded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ci2lab.evals.task import repo_root, setup_workspace

__all__ = [
    "CATEGORIES",
    "BenchTask",
    "VerifierSpec",
    "default_results_dir",
    "default_tasks_dir",
    "load_tasks",
    "setup_workspace",
]

CATEGORIES = frozenset({"cli", "qa", "bug", "feat", "safety"})
"""Allowed task families (see ``docs/BENCHMARKING.md`` §3)."""


@dataclass
class VerifierSpec:
    """How a single run is graded into a pass/fail.

    A task may grade on the agent's final answer (``answer_contains``), on shell
    commands run in the workspace after the agent finishes (``command`` /
    ``fail_to_pass`` / ``pass_to_pass``), and on which files the agent was
    allowed to touch (``forbid_paths``). A run is *solved* only when every
    configured check passes.
    """

    answer_contains: list[str] = field(default_factory=list)
    """Substrings that must all appear in the final answer (case-insensitive)."""

    answer_contains_ordered: bool = False
    """When true, ``answer_contains`` must appear in the given order."""

    command: str | None = None
    """Optional single command whose exit code must equal ``expect_exit``."""

    expect_exit: int = 0
    """Expected exit code for ``command``."""

    fail_to_pass: list[str] = field(default_factory=list)
    """Commands that must exit 0 *after* a correct fix (initially failing)."""

    pass_to_pass: list[str] = field(default_factory=list)
    """Regression commands that must still exit 0 (guard against breakage)."""

    forbid_paths: list[str] = field(default_factory=list)
    """Workspace paths the agent must not modify (checked via git)."""

    timeout_seconds: int = 120
    """Per-command timeout for the verifier subprocesses."""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> VerifierSpec:
        """Build a :class:`VerifierSpec` from a parsed ``verifier`` mapping.

        Args:
            data: The ``verifier`` block of a task JSON file, or ``None``.

        Returns:
            The populated spec; an empty spec when ``data`` is ``None``.
        """
        data = data or {}
        return cls(
            answer_contains=list(data.get("answer_contains") or []),
            answer_contains_ordered=bool(data.get("answer_contains_ordered", False)),
            command=data.get("command"),
            expect_exit=int(data.get("expect_exit", 0)),
            fail_to_pass=list(data.get("fail_to_pass") or []),
            pass_to_pass=list(data.get("pass_to_pass") or []),
            forbid_paths=list(data.get("forbid_paths") or []),
            timeout_seconds=int(data.get("timeout_seconds", 120)),
        )

    @property
    def has_oracle(self) -> bool:
        """Whether at least one positive grading check is configured."""
        return bool(self.answer_contains or self.command or self.fail_to_pass or self.pass_to_pass)

    @property
    def needs_git(self) -> bool:
        """Whether grading requires a git baseline (to detect forbidden edits)."""
        return bool(self.forbid_paths)


@dataclass
class BenchTask:
    """Declarative specification of one benchmark task."""

    id: str
    name: str
    category: str
    prompt: str
    workspace_setup: dict[str, Any] = field(default_factory=dict)
    hidden_setup: dict[str, Any] = field(default_factory=dict)
    verifier: VerifierSpec = field(default_factory=VerifierSpec)
    git_baseline: bool = False
    write_tools_enabled: bool | None = None
    max_rounds: int = 15
    timeout_seconds: int = 600
    k_samples: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchTask:
        """Build a :class:`BenchTask` from a parsed task JSON mapping.

        ``git_baseline`` defaults to true when the verifier declares
        ``forbid_paths`` or the task is a ``bug``/``feat`` task (both need a git
        baseline to grade), unless the task sets it explicitly.

        Args:
            data: Raw task mapping loaded from a task JSON file.

        Returns:
            The populated task.

        Raises:
            ValueError: If ``category`` is not one of :data:`CATEGORIES`.
        """
        category = str(data["category"])
        if category not in CATEGORIES:
            raise ValueError(
                f"Unknown task category {category!r}; expected one of {sorted(CATEGORIES)}"
            )
        verifier = VerifierSpec.from_dict(data.get("verifier"))
        git_baseline = data.get("git_baseline")
        if git_baseline is None:
            git_baseline = verifier.needs_git or category in {"bug", "feat"}
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            category=category,
            prompt=str(data["prompt"]),
            workspace_setup=dict(data.get("workspace_setup") or {}),
            hidden_setup=dict(data.get("hidden_setup") or {}),
            verifier=verifier,
            git_baseline=bool(git_baseline),
            write_tools_enabled=data.get("write_tools_enabled"),
            max_rounds=int(data.get("max_rounds", 15)),
            timeout_seconds=int(data.get("timeout_seconds", 600)),
            k_samples=data.get("k_samples"),
        )


def default_tasks_dir() -> Path:
    """Return the default benchmark tasks directory (``benchmarks/tasks``)."""
    return repo_root() / "benchmarks" / "tasks"


def default_results_dir() -> Path:
    """Return the default benchmark results directory (``benchmarks/results``)."""
    return repo_root() / "benchmarks" / "results"


def load_tasks(
    tasks_dir: Path | None = None,
    *,
    task_ids: list[str] | None = None,
) -> list[BenchTask]:
    """Load and parse benchmark task definitions from a directory of JSON files.

    Args:
        tasks_dir: Directory to scan; defaults to :func:`default_tasks_dir`.
        task_ids: When provided, keep only tasks whose ``id`` is in this list.

    Returns:
        The parsed tasks, sorted by file name.

    Raises:
        FileNotFoundError: If ``tasks_dir`` is not an existing directory.
    """
    base = tasks_dir or default_tasks_dir()
    if not base.is_dir():
        raise FileNotFoundError(f"Tasks directory does not exist: {base}")
    wanted = set(task_ids) if task_ids else None
    tasks: list[BenchTask] = []
    for path in sorted(base.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        task = BenchTask.from_dict(data)
        if wanted is not None and task.id not in wanted:
            continue
        tasks.append(task)
    return tasks
