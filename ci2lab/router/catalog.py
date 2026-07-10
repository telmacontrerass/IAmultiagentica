"""Model catalog loading."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from ci2lab.contracts import ModelSpec

CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog" / "models.json"


def load_model_catalog(path: Path = CATALOG_PATH) -> list[ModelSpec]:
    """Load and parse the model catalog from disk.

    Args:
        path: Path to the catalog JSON file; defaults to the bundled
            ``catalog/models.json``.

    Returns:
        Every catalog entry as a :class:`ModelSpec`.
    """
    with path.open("r", encoding="utf-8") as file:
        raw_models: list[dict[str, Any]] = json.load(file)
    return [ModelSpec(**model) for model in raw_models]


def find_model_by_tag(tag: str) -> ModelSpec | None:
    """Match catalog entry by id, ollama_tag, or display name."""
    normalized = tag.strip().lower()
    for model in load_model_catalog():
        if normalized in {
            model.id.lower(),
            model.ollama_tag.lower(),
            model.display_name.lower(),
        }:
            return model
    return None


def resolve_catalog_model(model_name: str) -> ModelSpec | None:
    """Return the catalog entry for ``model_name``, or ``None`` if absent.

    A thin alias of :func:`find_model_by_tag` kept for call-site readability.
    """
    return find_model_by_tag(model_name)


def suggest_similar_models(name: str, *, limit: int = 3, cutoff: float = 0.6) -> list[str]:
    """Return catalog Ollama tags closest to ``name`` — "did you mean" suggestions.

    Compares ``name`` against every catalog ``id`` and ``ollama_tag`` with
    difflib similarity and returns up to ``limit`` distinct tags, ordered by
    closeness. The ``cutoff`` keeps a genuinely custom (uncataloged) model from
    producing spurious suggestions: when nothing is similar enough the list is
    empty.

    Args:
        name: The (possibly mistyped) model id or tag the user supplied.
        limit: Maximum number of suggestions to return.
        cutoff: Minimum difflib similarity in ``[0, 1]`` for a candidate to count.

    Returns:
        Up to ``limit`` catalog Ollama tags, closest first; empty when ``name`` is
        blank or nothing clears ``cutoff``.
    """
    normalized = name.strip().lower()
    if not normalized:
        return []
    # Map every candidate string (id and tag, lower-cased) to the tag we would
    # actually suggest, so a match on either form resolves to one canonical tag.
    candidates: dict[str, str] = {}
    for model in load_model_catalog():
        candidates[model.id.lower()] = model.ollama_tag
        candidates[model.ollama_tag.lower()] = model.ollama_tag
    matches = difflib.get_close_matches(normalized, list(candidates), n=limit * 2, cutoff=cutoff)
    suggestions: list[str] = []
    for match in matches:
        tag = candidates[match]
        if tag not in suggestions:
            suggestions.append(tag)
        if len(suggestions) >= limit:
            break
    return suggestions
