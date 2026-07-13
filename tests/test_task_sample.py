"""Tests for the pre-registered stratified task sampler."""

from __future__ import annotations

from ci2lab.bench.task_sample import Task, stratified_sample


def _tasks() -> list[Task]:
    # Deliberately lopsided: 10 swe, 3 security, 1 games.
    return (
        [Task(f"swe-{i}", "software-engineering") for i in range(10)]
        + [Task(f"sec-{i}", "security") for i in range(3)]
        + [Task("games-0", "games")]
    )


def test_sample_is_deterministic_for_a_seed() -> None:
    first = stratified_sample(_tasks(), 6, seed=7)
    second = stratified_sample(_tasks(), 6, seed=7)
    assert first == second
    assert len(first) == 6


def test_different_seeds_can_differ() -> None:
    a = stratified_sample(_tasks(), 6, seed=1)
    b = stratified_sample(_tasks(), 6, seed=2)
    assert len(a) == len(b) == 6
    # Not a strict requirement of the algorithm, but with this fixture the seeds
    # should not collapse to the same list; if they did the seed would be inert.
    assert a != b


def test_sample_is_balanced_across_categories() -> None:
    # The dominant category must not swamp the sample: with 3 categories and n=6,
    # each contributes what it can before any category takes a second round.
    selected = stratified_sample(_tasks(), 6, seed=3)
    categories = [t.category for t in selected]
    assert categories.count("games") == 1  # the only one available
    assert categories.count("security") == 3  # all available
    assert categories.count("software-engineering") == 2


def test_requesting_more_than_available_returns_everything() -> None:
    tasks = _tasks()
    assert stratified_sample(tasks, 99, seed=1) == sorted(tasks, key=lambda t: t.task_id)


def test_zero_returns_empty() -> None:
    assert stratified_sample(_tasks(), 0, seed=1) == []


def test_result_is_sorted_for_a_stable_diff() -> None:
    selected = stratified_sample(_tasks(), 5, seed=11)
    assert selected == sorted(selected, key=lambda t: t.task_id)
