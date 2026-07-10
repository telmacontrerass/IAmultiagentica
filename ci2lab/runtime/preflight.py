"""Pre-flight model availability check for the direct CLI path.

Before ``ci2lab agent``/``chat`` hands a model to the harness, this verifies —
without any side effects — that the local Ollama runtime is reachable and that
the selected model is installed. If not, it raises a clear, actionable error
(including a "did you mean" suggestion for a mistyped tag) instead of letting the
run crash mid-flight with a cryptic Ollama error. It never downloads anything:
provisioning stays an explicit user action (``ollama pull`` / the interactive
menu's confirmed pull).
"""

from __future__ import annotations

from ci2lab.contracts.types import ModelSelection
from ci2lab.router.catalog import resolve_catalog_model, suggest_similar_models
from ci2lab.runtime.ollama import (
    fetch_installed_model_names,
    is_catalog_model_installed,
    ollama_base_url,
)

__all__ = ["ModelUnavailableError", "check_model_available"]


class ModelUnavailableError(RuntimeError):
    """The selected model cannot be served (Ollama down, or model not installed)."""


def check_model_available(selection: ModelSelection, *, timeout: float = 3.0) -> None:
    """Verify the selected model can serve, raising a clear error otherwise.

    Read-only: this never installs or downloads anything.

    Args:
        selection: The resolved model selection to check.
        timeout: Per-request timeout, in seconds, for the Ollama query.

    Raises:
        ModelUnavailableError: If the backend is Ollama and it is unreachable, or
            the model is not installed. The message names the fix (``ollama
            serve`` / ``ollama pull``) and suggests close catalog tags on a typo.
    """
    # Only the local Ollama runtime is ours to check. An OpenAI-compatible server
    # provisions models remotely, so there is nothing to verify here.
    if selection.backend != "ollama":
        return

    tag = selection.ollama_tag
    installed, error = fetch_installed_model_names(selection.backend_url, timeout=timeout)
    if error is not None:
        base = ollama_base_url(selection.backend_url)
        raise ModelUnavailableError(
            f"Ollama is not responding at {base} ({error}). "
            "Start it with `ollama serve` and try again."
        )

    if is_catalog_model_installed(tag, installed):
        return

    raise ModelUnavailableError(_missing_model_message(tag))


def _missing_model_message(tag: str) -> str:
    """Build the 'model not installed' message, adding a typo suggestion if apt."""
    parts = [f"Model {tag!r} is not installed."]
    # Only offer "did you mean" when the tag is not a real catalog entry — a known
    # model that simply is not pulled is not a typo, and a genuine custom model
    # should not be second-guessed.
    if resolve_catalog_model(tag) is None:
        suggestions = suggest_similar_models(tag)
        if suggestions:
            parts.append("Did you mean: " + ", ".join(suggestions) + "?")
    parts.append(
        f"Install it with `ollama pull {tag}`, or pick one with `ci2lab models recommend`."
    )
    return " ".join(parts)
