"""Public model resolution API (optional).

Auto-selects the top recommended model for a prompt. Production CLI/UI use
`router.selection.build_model_selection()` with an explicit user-chosen tag
via `pipeline.prepare_session()`.
"""

from __future__ import annotations

from ci2lab.contracts import HardwareProfile, ModelAlternative, ModelSelection
from ci2lab.hardware import scan_hardware
from ci2lab.router.intent import classify_intent
from ci2lab.router.recommend import recommend_models


def resolve_model(
    user_prompt: str,
    *,
    profile: HardwareProfile | None = None,
    force_model_id: str | None = None,
    prefer_installed: bool = True,
) -> ModelSelection:
    del prefer_installed

    profile = profile or scan_hardware()
    intent = classify_intent(user_prompt)
    recommendations = recommend_models(user_prompt, profile=profile, limit=5)
    if not recommendations:
        raise RuntimeError("No hay modelos en el catálogo que quepan en este hardware.")

    if force_model_id:
        normalized = force_model_id.lower()
        chosen = next(
            (
                model
                for model, _ in recommendations
                if model.id.lower() == normalized or model.ollama_tag.lower() == normalized
            ),
            None,
        )
        if chosen is None:
            raise RuntimeError(f"El modelo forzado no cabe o no existe: {force_model_id}")
    else:
        chosen = recommendations[0][0]

    alternatives = [
        ModelAlternative(model_id=model.id, ollama_tag=model.ollama_tag, reason=reason)
        for model, reason in recommendations[1:]
    ]

    return ModelSelection(
        model_id=chosen.id,
        ollama_tag=chosen.ollama_tag,
        display_name=chosen.display_name,
        tool_mode=chosen.tool_mode,
        supports_tools=chosen.supports_tools,
        context_length=chosen.context_length,
        intent=intent,
        hardware_tier=profile.hardware_tier,
        reason=f"Elegido porque cabe en tu hardware y encaja con la intención '{intent.category}'.",
        alternatives=alternatives,
    )
