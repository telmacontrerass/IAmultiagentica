"""Model catalog loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ci2lab.contracts import ModelSpec

CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog" / "models.json"


def load_model_catalog(path: Path = CATALOG_PATH) -> list[ModelSpec]:
    with path.open("r", encoding="utf-8") as file:
        raw_models: list[dict[str, Any]] = json.load(file)
    return [ModelSpec(**model) for model in raw_models]
