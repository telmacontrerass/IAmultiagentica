"""Recommend local models from hardware constraints."""

from __future__ import annotations

from dataclasses import dataclass

from ci2lab.contracts import HardwareProfile, IntentCategory, ModelSpec
from ci2lab.hardware import scan_hardware
from ci2lab.router.catalog import load_model_catalog
from ci2lab.router.intent import classify_intent

USE_CASES: tuple[IntentCategory, ...] = ("coding", "reasoning", "general", "rag")

CONTEXT_TARGETS: dict[IntentCategory, int] = {
    "coding": 32768,
    "rag": 32768,
    "reasoning": 16384,
    "translation": 8192,
    "vision": 8192,
    "voice": 8192,
    "edge": 4096,
    "general": 8192,
}


@dataclass(frozen=True)
class ScoredRecommendation:
    model: ModelSpec
    reason: str
    total_score: float
    quality_score: float
    speed_score: float
    fit_score: float
    context_score: float
    memory_required_gb: float
    memory_budget_gb: float
    remaining_memory_gb: float
    memory_usage_percent: float


@dataclass(frozen=True)
class DownloadPlanItem:
    use_cases: tuple[IntentCategory, ...]
    recommendation: ScoredRecommendation


def recommend_models(
    user_prompt: str = "",
    *,
    profile: HardwareProfile | None = None,
    limit: int = 5,
) -> list[tuple[ModelSpec, str]]:
    scored = score_recommendations(user_prompt, profile=profile, limit=limit)
    return [(item.model, item.reason) for item in scored]


def score_recommendations(
    user_prompt: str = "",
    *,
    profile: HardwareProfile | None = None,
    limit: int = 5,
) -> list[ScoredRecommendation]:
    profile = profile or scan_hardware()
    intent = classify_intent(user_prompt)
    return _score_for_category(intent.category, profile=profile, limit=limit)


def recommend_download_plan(
    *,
    profile: HardwareProfile | None = None,
    use_cases: tuple[IntentCategory, ...] = USE_CASES,
) -> list[DownloadPlanItem]:
    profile = profile or scan_hardware()
    by_model_id: dict[str, tuple[list[IntentCategory], ScoredRecommendation]] = {}

    for use_case in use_cases:
        scored = _score_for_category(use_case, profile=profile, limit=1)
        if not scored:
            continue
        chosen = scored[0]
        existing = by_model_id.get(chosen.model.id)
        if existing is None:
            by_model_id[chosen.model.id] = ([use_case], chosen)
            continue

        existing_cases, existing_choice = existing
        existing_cases.append(use_case)
        if chosen.total_score > existing_choice.total_score:
            by_model_id[chosen.model.id] = (existing_cases, chosen)

    plan = [
        DownloadPlanItem(use_cases=tuple(cases), recommendation=recommendation)
        for cases, recommendation in by_model_id.values()
    ]
    plan.sort(key=lambda item: item.recommendation.total_score, reverse=True)
    return plan


def _score_for_category(
    category: IntentCategory,
    *,
    profile: HardwareProfile,
    limit: int,
) -> list[ScoredRecommendation]:
    models = load_model_catalog()
    scored = [
        _score_recommendation(model, profile, category)
        for model in models
        if _model_fits(model, profile)
    ]
    scored.sort(key=lambda item: item.total_score, reverse=True)
    return scored[:limit]


def _model_fits(model: ModelSpec, profile: HardwareProfile) -> bool:
    return _memory_required_gb(model, profile) <= profile.inference_budget_gb


def _score_recommendation(
    model: ModelSpec,
    profile: HardwareProfile,
    category: IntentCategory,
) -> ScoredRecommendation:
    required_gb = _memory_required_gb(model, profile)
    budget_gb = profile.inference_budget_gb
    quality_score = _quality_score(model, category)
    speed_score = _speed_score(required_gb, budget_gb)
    fit_score = _fit_score(required_gb, budget_gb)
    context_score = _context_score(model, category)
    remaining_memory_gb = max(0.0, budget_gb - required_gb)
    memory_usage_percent = (required_gb / budget_gb * 100) if budget_gb > 0 else 0.0

    total_score = (
        quality_score * 0.42
        + speed_score * 0.22
        + fit_score * 0.24
        + context_score * 0.12
    )

    return ScoredRecommendation(
        model=model,
        reason=_fit_reason(model, profile),
        total_score=round(total_score, 3),
        quality_score=round(quality_score, 3),
        speed_score=round(speed_score, 3),
        fit_score=round(fit_score, 3),
        context_score=round(context_score, 3),
        memory_required_gb=required_gb,
        memory_budget_gb=budget_gb,
        remaining_memory_gb=round(remaining_memory_gb, 2),
        memory_usage_percent=round(memory_usage_percent, 1),
    )


def _quality_score(model: ModelSpec, category: IntentCategory) -> float:
    category_score = model.benchmark_score.get(category, model.benchmark_score.get("general", 0.0))
    tool_bonus = 0.04 if model.supports_tools else 0.0
    category_bonus = 0.05 if category in model.categories else 0.0
    return min(1.0, category_score + tool_bonus + category_bonus)


def _speed_score(required_gb: float, budget_gb: float) -> float:
    if budget_gb <= 0:
        return 0.0
    usage_ratio = required_gb / budget_gb
    return max(0.0, min(1.0, 1.05 - usage_ratio))


def _fit_score(required_gb: float, budget_gb: float) -> float:
    if budget_gb <= 0:
        return 0.0
    usage_ratio = required_gb / budget_gb
    if usage_ratio > 1:
        return 0.0
    distance_from_optimum = abs(usage_ratio - 0.65)
    return max(0.15, 1.0 - (distance_from_optimum / 0.65))


def _context_score(model: ModelSpec, category: IntentCategory) -> float:
    target = CONTEXT_TARGETS.get(category, CONTEXT_TARGETS["general"])
    return min(1.0, model.context_length / target)


def _fit_reason(model: ModelSpec, profile: HardwareProfile) -> str:
    if profile.inference_mode == "gpu" and profile.gpu_vendor != "apple":
        return (
            f"necesita ~{model.vram_min_gb:g} GB de VRAM; "
            f"tu presupuesto GPU es ~{profile.inference_budget_gb:g} GB"
        )
    return (
        f"necesita ~{model.ram_inference_gb:g} GB de RAM; "
        f"tu presupuesto es ~{profile.inference_budget_gb:g} GB"
    )


def _memory_required_gb(model: ModelSpec, profile: HardwareProfile) -> float:
    if profile.inference_mode == "gpu" and profile.gpu_vendor != "apple":
        return model.vram_min_gb
    return model.ram_inference_gb
