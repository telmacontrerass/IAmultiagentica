"""Small keyword-based intent classifier."""

from __future__ import annotations

from ci2lab.contracts import IntentCategory, IntentResult

SIGNALS: dict[IntentCategory, list[str]] = {
    "coding": ["code", "codigo", "programar", "python", "javascript", "bug", "repo", "refactor"],
    "rag": ["documentos", "pdf", "buscar", "rag", "base de datos", "archivos"],
    "reasoning": ["razonar", "matematicas", "plan", "analizar", "resolver", "logica"],
    "translation": ["traducir", "translate", "idioma", "ingles", "espanol"],
    "vision": ["imagen", "foto", "vision", "captura"],
    "voice": ["audio", "voz", "transcribir", "microfono"],
}


def classify_intent(user_prompt: str) -> IntentResult:
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
    difficulty = "high" if any(word in text for word in ["muy bien", "complejo", "grande"]) else "medium"
    return IntentResult(
        category=category,
        confidence=round(confidence, 2),
        signals=signals,
        difficulty=difficulty,
    )
