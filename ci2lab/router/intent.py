"""Small keyword-based intent classifier."""
# NOTE: the keyword lists below (and the difficulty trigger words) are matched
# against the user prompt; they intentionally keep Spanish terms so Spanish
# prompts still classify correctly. They are not user-facing text — do not
# translate or remove them.

from __future__ import annotations

from typing import Literal

from ci2lab.contracts import IntentCategory, IntentResult

SIGNALS: dict[IntentCategory, list[str]] = {
    "coding": ["code", "codigo", "programar", "python", "javascript", "bug", "repo", "refactor"],
    "rag": ["documentos", "pdf", "buscar", "rag", "base de datos", "archivos"],
    "reasoning": ["razonar", "matematicas", "plan", "analizar", "resolver", "logica"],
    "translation": ["traducir", "translate", "idioma", "ingles", "espanol"],
    "vision": [
        # Spanish
        "imagen",
        "foto",
        "vision",
        "captura",
        "analizar imagen",
        "describe imagen",
        "ver imagen",
        "fotografía",
        "pantalla",
        # English
        "image",
        "photo",
        "picture",
        "screenshot",
        "analyze image",
        "describe image",
        "vision model",
        "look at",
        "what is in",
        "identify",
        "detect objects",
        "ocr",
        "read image",
    ],
    "voice": ["audio", "voz", "transcribir", "microfono"],
}


def classify_intent(user_prompt: str) -> IntentResult:
    """Classify a user prompt into an intent category from keyword signals.

    Args:
        user_prompt: The raw user prompt to inspect.

    Returns:
        An :class:`IntentResult` with the best-matching category, a confidence
        score, the matched signal keywords, and an estimated difficulty.
    """
    text = user_prompt.lower()
    matches: list[tuple[IntentCategory, list[str]]] = []

    for category, keywords in SIGNALS.items():
        found = [keyword for keyword in keywords if keyword in text]
        if found:
            matches.append((category, found))

    if not matches:
        return IntentResult(category="general", confidence=0.45, signals=[])

    category, signals = max(matches, key=lambda item: len(item[1]))
    confidence = min(0.95, 0.55 + (0.12 * len(signals)))
    difficulty: Literal["low", "medium", "high"] = (
        "high" if any(word in text for word in ["muy bien", "complejo", "grande"]) else "medium"
    )
    return IntentResult(
        category=category,
        confidence=round(confidence, 2),
        signals=signals,
        difficulty=difficulty,
    )
