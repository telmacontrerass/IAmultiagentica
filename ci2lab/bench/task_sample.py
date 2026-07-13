"""Deterministic, stratified task sampling for a pre-registered benchmark subset.

One A6000 serves one model, so agent concurrency is serialized and the full
Terminal-Bench suite across four harnesses is out of reach. We therefore run a
**subset** — which is only honest if the subset is fixed *before* any result is
seen. Post-hoc task selection is the easiest way to accidentally manufacture a
finding, and a reviewer will assume it happened unless the protocol rules it out.

So: sample once, deterministically (fixed seed), stratified across the benchmark's
task categories so no domain dominates, and commit the resulting list. The run then
takes that file as input. Re-running this with the same seed and inputs reproduces
the identical list, which is what makes the pre-registration checkable.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

__all__ = ["Task", "stratified_sample"]


@dataclass(frozen=True)
class Task:
    """A benchmark task and the category it belongs to."""

    task_id: str
    category: str


def stratified_sample(tasks: list[Task], n: int, *, seed: int) -> list[Task]:
    """Pick ``n`` tasks spread as evenly as possible across categories.

    Categories are filled round-robin, so a category with many tasks cannot swamp
    the sample; within a category the pick is a seeded shuffle. When ``n`` exceeds
    the number of available tasks, every task is returned.

    Args:
        tasks: All candidate tasks, each tagged with its category.
        n: How many tasks to select.
        seed: Seed fixing the selection. Record it alongside the results.

    Returns:
        The selected tasks, sorted by ``task_id`` for a stable, diffable list.
    """
    if n <= 0:
        return []
    if n >= len(tasks):
        return sorted(tasks, key=lambda t: t.task_id)

    by_category: dict[str, list[Task]] = defaultdict(list)
    for task in tasks:
        by_category[task.category].append(task)

    rng = random.Random(seed)
    pools: dict[str, list[Task]] = {}
    for category in sorted(by_category):
        pool = sorted(by_category[category], key=lambda t: t.task_id)
        rng.shuffle(pool)
        pools[category] = pool

    selected: list[Task] = []
    # Round-robin across categories until the quota is met, so the sample stays
    # balanced even when category sizes are wildly uneven.
    while len(selected) < n:
        progressed = False
        for category in sorted(pools):
            if len(selected) == n:
                break
            pool = pools[category]
            if pool:
                selected.append(pool.pop())
                progressed = True
        if not progressed:
            break

    return sorted(selected, key=lambda t: t.task_id)
