"""Vision helpers for the ci2lab harness.

Provides three public functions:

  is_vision_model(model_name)
      Name-based heuristic: returns True when the model tag suggests the
      model can natively accept image input.  Errs toward True — a false
      positive (text model flagged as vision) is safer than a false negative
      (image silently dropped before it reaches the model).

  build_vision_content(text, image_paths)
      Encodes local image files as base64 and returns an OpenAI-style
      multipart content list for use as the ``content`` field of a user
      message.

  analyze_image(image_path, backend_url, model_tag)
      Sends an image to a vision-language model via the OpenAI-compat API
      and returns the model's text description.

Adapted from:
  Odysseus src/chat_helpers.py        — is_vision_model keyword list + VL regex
  Odysseus src/document_processor.py  — build_user_content (image section)
                                        and analyze_image_with_vl_result
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vision model detection
# ---------------------------------------------------------------------------

# Model-name substrings that signal native image input.  Keep this broad —
# especially for local Ollama models that ship under many names.  Missing a
# match silently drops the image, which is the worse failure.
_VISION_MODEL_KEYWORDS = (
    # hosted
    "gpt-4o", "gpt-4.1", "gpt-4.5", "gpt-4-turbo", "gpt-4-vision",
    "claude-sonnet", "claude-opus", "claude-haiku", "gemini",
    # open / local
    "vision", "multimodal", "llava", "bakllava", "moondream", "pixtral", "minicpm",
    "internvl", "cogvlm", "qwen-vl", "qwen2-vl", "qwen3-vl", "qwen3vl",
    # multimodal families whose names don't contain "vision"/"vl" but DO accept
    # images — Gemma 3/4, Llama 4, Mistral Small 3.1/3.2, Phi-4 multimodal
    "gemma-3", "gemma3", "gemma-4", "gemma4",
    "llama-4", "llama4",
    "mistral-small-3.1", "mistral-small3.1", "mistral-small-3.2", "mistral-small3.2",
    "phi-4", "phi4",
    # Zhipu / GLM vision variants
    "glm-4.5v", "glm-4.6v", "glm-5v",
    # Qwen3.5 and Qwen3.6 are vision-capable on Ollama but have no "vl" in
    # the tag name — add explicit prefixes so tags like qwen3.5:4b are caught
    "qwen3.5", "qwen3.6",
    # IBM Granite 3.2 Vision — tag is "granite3.2-vision" so "vision" already
    # matches, but add the family prefix as a safety net for tag variants
    "granite3.2",
)

# Catches the "*-VL-*" / "*VL*" family not covered by a literal keyword above
# (e.g. Qwen2.5-VL and various quantised tags): standalone "vl" token + "vlm".
_VISION_VL_RE = re.compile(r"(?<![a-z])vl(?![a-z])|vlm")


def is_vision_model(model_name: str | None) -> bool:
    """Return True when *model_name* appears to support native image input.

    Uses keyword substring matching followed by a regex for standalone "vl"
    tokens.  Errs toward True: a misclassified text model receiving an
    ``image_url`` block will simply ignore it, whereas a vision model that
    never gets the image block produces a silently wrong answer.
    """
    m = (model_name or "").lower()
    if any(kw in m for kw in _VISION_MODEL_KEYWORDS):
        return True
    return bool(_VISION_VL_RE.search(m))


# ---------------------------------------------------------------------------
# Multimodal message building
# ---------------------------------------------------------------------------

_MIME_FROM_EXT: dict[str, str] = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".gif": "gif",
    ".webp": "webp",
    ".bmp": "bmp",
    ".tiff": "tiff",
    ".tif": "tiff",
}


def build_vision_content(
    text: str,
    image_paths: list[str],
) -> list[dict[str, Any]]:
    """Build an OpenAI-style multipart content list for a user message.

    Returns a list starting with a text block followed by one ``image_url``
    block per successfully encoded image.  Images that cannot be read are
    logged and a note is appended to the text block instead of failing.

    The returned list is ready to be used as ``{"role": "user", "content": ...}``.

    Adapted from Odysseus ``src/document_processor.build_user_content``
    (image-encoding section).
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]

    for path in image_paths:
        if not path:
            continue
        if not os.path.exists(path):
            logger.warning("Vision: image path not found: %s", path)
            content[0]["text"] += f"\n\n[Image not found: {path}]"
            continue

        ext = Path(path).suffix.lower()
        img_format = _MIME_FROM_EXT.get(ext) or (
            (mimetypes.guess_type(path)[0] or "").split("/")[-1] or "jpeg"
        )

        try:
            with open(path, "rb") as fh:
                encoded = base64.b64encode(fh.read()).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/{img_format};base64,{encoded}"},
            })
        except OSError as exc:
            logger.error("Vision: failed to encode image %s: %s", path, exc)
            content[0]["text"] += (
                f"\n\n[Image attached but could not be read: {Path(path).name}]"
            )

    return content


# ---------------------------------------------------------------------------
# VL fallback analysis
# ---------------------------------------------------------------------------

def analyze_image(
    image_path: str,
    backend_url: str,
    model_tag: str,
    timeout: float = 120.0,
) -> str:
    """Call a vision-language model and return a text description of the image.

    Parameters
    ----------
    image_path:
        Absolute path to the image file.
    backend_url:
        OpenAI-compat base URL, e.g. ``http://localhost:11434/v1``.
    model_tag:
        Ollama tag of the vision model, e.g. ``llava`` or ``qwen3-vl``.
    timeout:
        HTTP timeout in seconds (default 120 — VL inference can be slow).

    Returns the model's description string, or a human-readable error string
    that the caller can inject into the prompt and continue.  Never raises.

    Adapted from Odysseus ``src/document_processor.analyze_image_with_vl_result``.
    """
    if not image_path or not os.path.exists(image_path):
        return f"[Image not found: {image_path}]"

    if not backend_url or not model_tag:
        return (
            "[Vision: no vision model configured — set vision_model in "
            "AgentConfig or ~/.ci2lab/settings.json]"
        )

    ext = Path(image_path).suffix.lower()
    img_format = _MIME_FROM_EXT.get(ext, "jpeg")

    try:
        with open(image_path, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("utf-8")
    except OSError as exc:
        logger.error("Vision: failed to read image %s: %s", image_path, exc)
        return f"[Image could not be read: {Path(image_path).name}]"

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image in detail."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/{img_format};base64,{encoded}"
                    },
                },
            ],
        }
    ]

    try:
        from ci2lab.contracts.types import ModelSelection
        from ci2lab.harness.llm_client import LLMClient

        vl_selection = ModelSelection(
            model_id=model_tag,
            ollama_tag=model_tag,
            display_name=model_tag,
            backend_url=backend_url,
            supports_tools=False,
            tool_mode="fenced",
            context_length=8192,
            max_tokens=1024,
            temperature=0.2,
        )
        client = LLMClient(vl_selection, timeout=timeout)
        response = client.chat(messages)
        return response.content or "[Vision model returned an empty response]"

    except Exception as exc:  # noqa: BLE001
        logger.error("Vision analysis failed for %s: %s", image_path, exc)
        return f"[Vision analysis failed: {exc}]"
