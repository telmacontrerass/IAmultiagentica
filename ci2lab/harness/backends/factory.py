"""Selection of the concrete :class:`LLMBackend` for a model selection.

This is the single seam that maps a provider name to its transport. Adding
support for a new inference server means adding a backend class and one entry
to :data:`_BACKENDS`; nothing else in the harness needs to change.
"""

from __future__ import annotations

from collections.abc import Callable

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.backends.base import LLMBackend
from ci2lab.harness.backends.ollama import OllamaBackend
from ci2lab.harness.backends.openai_compat import OpenAICompatBackend

_BackendFactory = Callable[[ModelSelection, float, int], LLMBackend]


def _ollama(selection: ModelSelection, timeout: float, vision_image_count: int) -> LLMBackend:
    return OllamaBackend(selection, timeout, vision_image_count=vision_image_count)


def _openai(selection: ModelSelection, timeout: float, vision_image_count: int) -> LLMBackend:
    return OpenAICompatBackend(selection, timeout, vision_image_count=vision_image_count)


_BACKENDS: dict[str, _BackendFactory] = {
    "ollama": _ollama,
    "openai": _openai,
}


def create_backend(
    selection: ModelSelection,
    timeout: float = 300.0,
    *,
    vision_image_count: int = 0,
) -> LLMBackend:
    """Build the backend for ``selection.backend``.

    Args:
        selection: The resolved model selection; ``selection.backend`` chooses
            the transport.
        timeout: Per-request timeout in seconds.
        vision_image_count: Number of images in the request, forwarded to the
            backend for clearer multimodal error messages.

    Returns:
        A ready-to-use :class:`LLMBackend`. Unknown provider names fall back to
        the OpenAI-compatible transport, which is the de-facto standard for
        local inference servers.
    """
    factory = _BACKENDS.get(selection.backend, _openai)
    return factory(selection, timeout, vision_image_count)
