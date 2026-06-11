"""Router de intención y selección de modelos."""

from ci2lab.router.catalog import find_model_by_tag, load_model_catalog
from ci2lab.router.intent import classify_intent
from ci2lab.router.recommend import recommend_download_plan, recommend_models, score_recommendations
from ci2lab.router.resolve import resolve_model
from ci2lab.router.selection import build_model_selection

__all__ = [
    "build_model_selection",
    "classify_intent",
    "find_model_by_tag",
    "load_model_catalog",
    "recommend_download_plan",
    "recommend_models",
    "resolve_model",
    "score_recommendations",
]
