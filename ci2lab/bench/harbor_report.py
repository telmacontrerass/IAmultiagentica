"""Aggregate Harbor job directories into the paper's main results table.

Reads one job directory per condition (ci2lab / ci2lab-multi / opencode /
deepagents), each produced by ``harbor run -o <dir>``, and emits Table 1 of
[`docs/BENCHMARK_DESIGN.md`](../../docs/BENCHMARK_DESIGN.md): pass@1 with a
bootstrap CI, the tool-call correctness ladder, and tokens per solved task.

Two design rules, both there to stop the table from lying:

**Unreadable trials are counted and reported, never silently failed.** A trial
whose outcome cannot be determined is not the same as a failed trial. Treating one
as the other would quietly bias pass@1 downward and hide a broken pipeline behind
a plausible-looking number, so such trials are excluded from the rates and
surfaced in an explicit ``unreadable`` count that the caller is expected to look at.

**Tool-call rates never appear without their denominator.** The correctness rate is
gameable by a harness that simply calls fewer tools, so the absolute attempt count
is printed beside it in every row.

Usage::

    python -m ci2lab.bench.harbor_report jobs/ci2lab jobs/opencode
    python -m ci2lab.bench.harbor_report ci2lab=jobs/run1 opencode=jobs/run2
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ci2lab.bench.metrics import bootstrap_ci, pass_at_k
from ci2lab.harness.tool_metrics import ToolCallQuality

__all__ = [
    "ConditionSummary",
    "TrialRecord",
    "load_job_dir",
    "main",
    "render_markdown_table",
    "summarize_condition",
]


@dataclass
class TrialRecord:
    """One Harbor trial: did it solve the task, at what token and tool cost."""

    task_id: str
    resolved: bool | None
    """``None`` when the outcome could not be determined (a broken/incomplete trial)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_call_quality: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConditionSummary:
    """Aggregated results for one harness condition."""

    label: str
    tasks: int = 0
    trials: int = 0
    unreadable: int = 0
    """Trials whose outcome could not be read. Excluded from every rate below."""

    pass_at_1: float | None = None
    pass_at_1_ci: tuple[float, float] | None = None
    pass_hat_k: float | None = None
    """Share of tasks solved on *every* attempt (reliability, cf. tau-bench pass^k)."""

    total_tokens: int = 0
    solved_trials: int = 0
    quality: ToolCallQuality = field(default_factory=ToolCallQuality)

    @property
    def tokens_per_solved(self) -> float | None:
        """Total tokens spent divided by trials solved, or ``None`` if none solved."""
        if self.solved_trials == 0:
            return None
        return self.total_tokens / self.solved_trials


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _extract_resolved(data: dict[str, Any]) -> bool | None:
    """Decide whether a trial solved its task.

    Harbor's verifier reports ``rewards`` as a mapping; a Terminal-Bench task is
    resolved only when it scores full marks. When several rewards are present we
    require *all* of them, matching Harbor's "resolved only when every unit test
    passes" semantics.

    Args:
        data: A parsed per-trial ``results.json``.

    Returns:
        ``True``/``False``, or ``None`` when no reward could be found — which is a
        broken trial, not a failed one.
    """
    verifier = data.get("verifier_result")
    if not isinstance(verifier, dict):
        return None
    rewards = verifier.get("rewards")
    if not isinstance(rewards, dict) or not rewards:
        return None
    values = [v for v in rewards.values() if isinstance(v, int | float)]
    if not values:
        return None
    return all(float(v) >= 1.0 for v in values)


def _extract_task_id(data: dict[str, Any], path: Path) -> str:
    """Recover the task id from the trial payload, falling back to the directory."""
    for key in ("task_id", "task_name"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    task = data.get("task")
    if isinstance(task, dict):
        for key in ("id", "name"):
            value = task.get(key)
            if isinstance(value, str) and value:
                return value
    # Harbor lays trials out as <job>/<task_id>/<trial>/results.json.
    return path.parent.parent.name or path.parent.name


def load_job_dir(job_dir: Path) -> list[TrialRecord]:
    """Read every per-trial ``results.json`` under a Harbor job directory.

    The job-root aggregate is skipped: it reports Harbor's own pass@k, but not the
    per-task detail needed for a bootstrap CI, and it carries no tool-call metrics.

    Args:
        job_dir: A directory passed to ``harbor run -o``.

    Returns:
        One :class:`TrialRecord` per trial found (possibly empty).
    """
    records: list[TrialRecord] = []
    for path in sorted(job_dir.rglob("results.json")):
        if path.parent == job_dir:
            continue  # the job-root aggregate, not a trial
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            records.append(TrialRecord(task_id=path.parent.name, resolved=None))
            continue
        if not isinstance(data, dict):
            records.append(TrialRecord(task_id=path.parent.name, resolved=None))
            continue

        agent = data.get("agent_result")
        agent = agent if isinstance(agent, dict) else {}
        metadata = agent.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        quality = metadata.get("tool_call_quality")
        quality = quality if isinstance(quality, dict) else {}

        records.append(
            TrialRecord(
                task_id=_extract_task_id(data, path),
                resolved=_extract_resolved(data),
                prompt_tokens=_as_int(agent.get("n_input_tokens")),
                completion_tokens=_as_int(agent.get("n_output_tokens")),
                tool_call_quality=quality,
            )
        )
    return records


def summarize_condition(label: str, records: list[TrialRecord]) -> ConditionSummary:
    """Aggregate one condition's trials into a table row.

    pass@1 is the unbiased estimator averaged over tasks (so a task with more
    attempts does not get more weight), and its CI is bootstrapped over the
    per-task values. Unreadable trials are dropped from the rates and counted.

    Args:
        label: Display name for the condition.
        records: Trials belonging to this condition.

    Returns:
        The aggregated :class:`ConditionSummary`.
    """
    summary = ConditionSummary(label=label, trials=len(records))

    by_task: dict[str, list[TrialRecord]] = defaultdict(list)
    for record in records:
        if record.resolved is None:
            summary.unreadable += 1
            continue
        by_task[record.task_id].append(record)

        summary.total_tokens += record.prompt_tokens + record.completion_tokens
        if record.resolved:
            summary.solved_trials += 1

        quality = record.tool_call_quality
        if quality:
            summary.quality.attempts += _as_int(quality.get("attempts"))
            summary.quality.raw_correct += _as_int(quality.get("raw_correct"))
            summary.quality.effective_correct += _as_int(quality.get("effective_correct"))
            summary.quality.repaired += _as_int(quality.get("repaired"))
            summary.quality.malformed += _as_int(quality.get("malformed"))
            summary.quality.hallucinated_tool += _as_int(quality.get("hallucinated_tool"))
            summary.quality.invalid_arguments += _as_int(quality.get("invalid_arguments"))
            summary.quality.execution_error += _as_int(quality.get("execution_error"))

    summary.tasks = len(by_task)
    if not by_task:
        return summary

    per_task_pass1: list[float] = []
    per_task_all: list[float] = []
    for task_records in by_task.values():
        n = len(task_records)
        c = sum(1 for r in task_records if r.resolved)
        per_task_pass1.append(pass_at_k(n, c, 1))
        per_task_all.append(1.0 if c == n and n > 0 else 0.0)

    summary.pass_at_1 = sum(per_task_pass1) / len(per_task_pass1)
    summary.pass_at_1_ci = bootstrap_ci(per_task_pass1)
    summary.pass_hat_k = sum(per_task_all) / len(per_task_all)
    return summary


# The table is written to a terminal and pasted into the paper, so keep every cell
# ASCII: a cp1252 console turns an en/em dash into mojibake.
_MISSING = "-"


def _pct(value: float | None) -> str:
    return _MISSING if value is None else f"{value * 100:.1f}%"


def _rate(numerator: int, denominator: int) -> str:
    return _MISSING if denominator == 0 else f"{numerator / denominator * 100:.1f}%"


def _pass_cell(summary: ConditionSummary) -> str:
    if summary.pass_at_1 is None:
        return _MISSING
    cell = _pct(summary.pass_at_1)
    if summary.pass_at_1_ci is not None:
        low, high = summary.pass_at_1_ci
        cell += f" [{low * 100:.1f}, {high * 100:.1f}]"
    return cell


def render_markdown_table(summaries: list[ConditionSummary]) -> str:
    """Render the conditions as the paper's main results table.

    Args:
        summaries: One summary per condition, in display order.

    Returns:
        A GitHub-flavoured Markdown table, plus any caveats that apply.
    """
    header = (
        "| Harness | pass@1 (95% CI) | pass^k | Tool-call attempts | Raw TCR | "
        "Effective TCR | Repair rate | Hallucinated | Malformed | Invalid args | "
        "Tokens / solved |"
    )
    divider = "| --- " * 11 + "|"
    lines = [header, divider]

    for s in summaries:
        q = s.quality
        tokens = _MISSING if s.tokens_per_solved is None else f"{s.tokens_per_solved:,.0f}"
        attempts = _MISSING if q.attempts == 0 else f"{q.attempts:,}"
        lines.append(
            f"| {s.label} | {_pass_cell(s)} | {_pct(s.pass_hat_k)} | {attempts} | "
            f"{_pct(q.raw_correctness_rate)} | {_pct(q.effective_correctness_rate)} | "
            f"{_pct(q.repair_rate)} | {_rate(q.hallucinated_tool, q.attempts)} | "
            f"{_rate(q.malformed, q.attempts)} | "
            f"{_rate(q.invalid_arguments, q.attempts)} | {tokens} |"
        )

    notes: list[str] = []
    for s in summaries:
        if s.unreadable:
            notes.append(
                f"- **{s.label}: {s.unreadable} of {s.trials} trials were unreadable** "
                "and are excluded from every rate above. Investigate before citing "
                "these numbers: this usually means a broken run, not a hard task."
            )
        if s.quality.attempts == 0 and s.trials:
            notes.append(
                f"- {s.label} reported no tool-call trace, so its tool-call columns "
                "are blank rather than zero. (deepagents emits no trajectory.)"
            )
    if notes:
        lines.append("")
        lines.extend(notes)

    lines.append("")
    lines.append(
        "Tool-call rates are shares of *attempts*, not of trials, and are shown "
        "beside the absolute attempt count: a harness that calls fewer tools can "
        "score a high rate by doing less, so the rate is meaningless without it."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Aggregate the given Harbor job directories and print the results table.

    Args:
        argv: ``label=path`` or bare ``path`` arguments. When omitted, the label is
            the directory name. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (``0`` on success, ``2`` when no jobs were given).
    """
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    summaries: list[ConditionSummary] = []
    for arg in args:
        label, _, raw_path = arg.partition("=")
        path = Path(raw_path or label)
        if not raw_path:
            label = path.name
        if not path.is_dir():
            print(f"error: not a directory: {path}", file=sys.stderr)
            return 2
        summaries.append(summarize_condition(label, load_job_dir(path)))

    print(render_markdown_table(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
