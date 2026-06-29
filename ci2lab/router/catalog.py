"""Model catalog loading."""

from __future__ import annotations

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
