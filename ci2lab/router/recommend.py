"""Recommend local models from hardware constraints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ci2lab.contracts import HardwareProfile, IntentCategory, ModelSpec
from ci2lab.hardware import scan_hardware
from ci2lab.router.catalog import load_model_catalog
from ci2lab.router.intent import classify_intent

USE_CASES: tuple[IntentCategory, ...] = ("coding", "reasoning", "general", "rag")

MemoryFitStatus = Literal["ok_now", "requires_cleanup", "not_recommended"]
RecommendationStatus = Literal["OK_NOW", "OK_IF_MEMORY_FREED", "NOT_RECOMMENDED"]

_STATUS_LABELS: dict[RecommendationStatus, str] = {
    "OK_NOW": "Fits now",
    "OK_IF_MEMORY_FREED": "Fits if memory is freed",
    "NOT_RECOMMENDED": "Not recommended",
}

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
    memory_fit_status: MemoryFitStatus
    requires_memory_cleanup: bool
    fit_label: str
    theoretical_fit: bool
    current_fit: bool
    recommendation_status: RecommendationStatus


@dataclass(frozen=True)
class ModelMemoryClassification:
    required_gb: float
    theoretical_fit: bool
    current_fit: bool
    recommendation_status: RecommendationStatus
    requires_memory_cleanup: bool
    fit_label: str


@dataclass(frozen=True)
class DownloadPlanItem:
    use_cases: tuple[IntentCategory, ...]
    recommendation: ScoredRecommendation
    installed: bool = False


@dataclass(frozen=True)
class DisplayRecommendation:
    item: ScoredRecommendation
    installed: bool

    @property
    def installation_label(self) -> str:
        return "Already installed" if self.installed else "To download"


def recommendation_pool_size(limit: int) -> int:
    return max(limit * 4, 20)


def pick_scored_recommendation(
    scored: list[ScoredRecommendation],
    installed_names: set[str],
) -> tuple[ScoredRecommendation | None, ScoredRecommendation | None]:
    """Return (download_pick, installed_match) from a score-ordered pool."""
    from ci2lab.runtime.ollama import is_catalog_model_installed

    installed_match: ScoredRecommendation | None = None
    download_pick: ScoredRecommendation | None = None

    for item in scored:
        if is_catalog_model_installed(item.model.ollama_tag, installed_names):
            if installed_match is None:
                installed_match = item
            continue
        download_pick = item
        break

    if download_pick is None and scored:
        download_pick = scored[0]
        if installed_match is None and is_catalog_model_installed(
            scored[0].model.ollama_tag,
            installed_names,
        ):
            installed_match = scored[0]

    return download_pick, installed_match


def build_display_recommendations(
    scored: list[ScoredRecommendation],
    installed_names: set[str],
    *,
    limit: int,
) -> list[DisplayRecommendation]:
    """Combine installed matches with download suggestions for display."""
    from ci2lab.runtime.ollama import is_catalog_model_installed

    if not scored:
        return []

    tagged = [
        (item, is_catalog_model_installed(item.model.ollama_tag, installed_names))
        for item in scored
    ]
    installed_items = [item for item, is_installed in tagged if is_installed]
    download_items = [item for item, is_installed in tagged if not is_installed]

    result: list[DisplayRecommendation] = []
    seen: set[str] = set()

    def add(item: ScoredRecommendation, installed: bool) -> None:
        if item.model.id in seen:
            return
        seen.add(item.model.id)
        result.append(DisplayRecommendation(item=item, installed=installed))

    for item in installed_items[:2]:
        add(item, True)

    for item in download_items:
        if len(result) >= limit:
            break
        add(item, False)

    if len(result) < limit:
        for item, is_installed in tagged:
            if len(result) >= limit:
                break
            add(item, is_installed)

    return result[:limit]


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


def _sort_download_plan_entries(entries: list[DownloadPlanItem]) -> list[DownloadPlanItem]:
    use_case_order = {use_case: index for index, use_case in enumerate(USE_CASES)}
    return sorted(
        entries,
        key=lambda item: (
            use_case_order.get(item.use_cases[0], len(USE_CASES)),
            not item.installed,
            -item.recommendation.total_score,
        ),
    )


def recommend_download_plan(
    *,
    profile: HardwareProfile | None = None,
    use_cases: tuple[IntentCategory, ...] = USE_CASES,
    installed_names: set[str] | None = None,
) -> list[DownloadPlanItem]:
    profile = profile or scan_hardware()
    installed_names = installed_names or set()
    entries: list[DownloadPlanItem] = []

    for use_case in use_cases:
        scored = _score_for_category(
            use_case,
            profile=profile,
            limit=recommendation_pool_size(1),
        )
        download_pick, installed_match = pick_scored_recommendation(scored, installed_names)

        if installed_match is not None:
            entries.append(
                DownloadPlanItem(
                    use_cases=(use_case,),
                    recommendation=installed_match,
                    installed=True,
                )
            )

        if download_pick is not None and (
            installed_match is None
            or download_pick.model.id != installed_match.model.id
        ):
            entries.append(
                DownloadPlanItem(
                    use_cases=(use_case,),
                    recommendation=download_pick,
                    installed=False,
                )
            )

    return _sort_download_plan_entries(entries)


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
        if model_fits(model, profile)
    ]
    scored.sort(key=lambda item: item.total_score, reverse=True)
    return scored[:limit]


def classify_model_memory(
    required_gb: float,
    profile: HardwareProfile,
) -> ModelMemoryClassification:
    theoretical_gb = _effective_theoretical_budget(profile)
    available_gb = _effective_available_budget(profile)
    theoretical_fit = required_gb <= theoretical_gb
    current_fit = required_gb <= available_gb

    if theoretical_fit and current_fit:
        status: RecommendationStatus = "OK_NOW"
        requires_cleanup = False
    elif theoretical_fit:
        status = "OK_IF_MEMORY_FREED"
        requires_cleanup = True
    else:
        status = "NOT_RECOMMENDED"
        requires_cleanup = False

    return ModelMemoryClassification(
        required_gb=required_gb,
        theoretical_fit=theoretical_fit,
        current_fit=current_fit,
        recommendation_status=status,
        requires_memory_cleanup=requires_cleanup,
        fit_label=_STATUS_LABELS[status],
    )


def classify_memory_fit(
    required_gb: float,
    profile: HardwareProfile,
) -> tuple[MemoryFitStatus, bool, str]:
    """Compatibility with tests/legacy code."""
    classification = classify_model_memory(required_gb, profile)
    legacy_status: MemoryFitStatus
    if classification.recommendation_status == "OK_NOW":
        legacy_status = "ok_now"
    elif classification.recommendation_status == "OK_IF_MEMORY_FREED":
        legacy_status = "requires_cleanup"
    else:
        legacy_status = "not_recommended"
    return legacy_status, classification.requires_memory_cleanup, classification.fit_label


def _effective_theoretical_budget(profile: HardwareProfile) -> float:
    if profile.inference_budget_theoretical_gb > 0.0:
        return profile.inference_budget_theoretical_gb
    return profile.inference_budget_gb


def _effective_available_budget(profile: HardwareProfile) -> float:
    if profile.inference_budget_available_gb > 0.0:
        return profile.inference_budget_available_gb
    return profile.inference_budget_gb


def model_fits(model: ModelSpec, profile: HardwareProfile) -> bool:
    """True if the model fits within this machine's theoretical budget.

    Single source of truth for CLI, router, and UI.
    """
    required_gb = _memory_required_gb(model, profile)
    return classify_model_memory(required_gb, profile).theoretical_fit


def _score_recommendation(
    model: ModelSpec,
    profile: HardwareProfile,
    category: IntentCategory,
) -> ScoredRecommendation:
    required_gb = _memory_required_gb(model, profile)
    budget_gb = profile.inference_budget_gb
    available_gb = _effective_available_budget(profile)
    classification = classify_model_memory(required_gb, profile)
    memory_fit_status, requires_memory_cleanup, fit_label = classify_memory_fit(
        required_gb,
        profile,
    )
    quality_score = _quality_score(model, category)
    speed_score = _speed_score(required_gb, budget_gb)
    fit_score = _fit_score(required_gb, budget_gb)
    context_score = _context_score(model, category)
    remaining_memory_gb = max(0.0, available_gb - required_gb)
    memory_usage_percent = (required_gb / budget_gb * 100) if budget_gb > 0 else 0.0

    total_score = (
        quality_score * 0.42
        + speed_score * 0.22
        + fit_score * 0.24
        + context_score * 0.12
    )

    return ScoredRecommendation(
        model=model,
        reason=_fit_reason(profile, classification=classification),
        total_score=round(total_score, 3),
        quality_score=round(quality_score, 3),
        speed_score=round(speed_score, 3),
        fit_score=round(fit_score, 3),
        context_score=round(context_score, 3),
        memory_required_gb=required_gb,
        memory_budget_gb=budget_gb,
        remaining_memory_gb=round(remaining_memory_gb, 2),
        memory_usage_percent=round(memory_usage_percent, 1),
        memory_fit_status=memory_fit_status,
        requires_memory_cleanup=requires_memory_cleanup,
        fit_label=fit_label,
        theoretical_fit=classification.theoretical_fit,
        current_fit=classification.current_fit,
        recommendation_status=classification.recommendation_status,
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


def _fit_reason(
    profile: HardwareProfile,
    *,
    classification: ModelMemoryClassification,
) -> str:
    required_gb = classification.required_gb
    available_gb = _effective_available_budget(profile)
    theoretical_gb = _effective_theoretical_budget(profile)

    if profile.inference_mode == "gpu" and profile.gpu_vendor != "apple":
        resource = "VRAM"
    else:
        resource = "RAM"

    if classification.recommendation_status == "OK_NOW":
        return (
            f"needs ~{required_gb:g} GB of {resource}; "
            f"fits now (~{available_gb:g} GB safely available)"
        )
    if classification.recommendation_status == "OK_IF_MEMORY_FREED":
        return (
            f"needs ~{required_gb:g} GB; fits theoretically "
            f"(~{theoretical_gb:g} GB), but right now only "
            f"~{available_gb:g} GB are safely available"
        )
    return (
        f"needs ~{required_gb:g} GB of {resource}; "
        f"exceeds the machine's theoretical budget (~{theoretical_gb:g} GB)"
    )


def _memory_required_gb(model: ModelSpec, profile: HardwareProfile) -> float:
    if profile.inference_mode == "gpu" and profile.gpu_vendor != "apple":
        return model.vram_min_gb
    return model.ram_inference_gb
