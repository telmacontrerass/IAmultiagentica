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
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ci2lab.harness.tools.filesystem_parts.documents import pdf_needs_vision

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vision model detection
# ---------------------------------------------------------------------------

# Model-name substrings that signal native image input.  Keep this broad —
# especially for local Ollama models that ship under many names.  Missing a
# match silently drops the image, which is the worse failure.
_VISION_MODEL_KEYWORDS = (
    # hosted
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.5",
    "gpt-4-turbo",
    "gpt-4-vision",
    "claude-sonnet",
    "claude-opus",
    "claude-haiku",
    "gemini",
    # open / local
    "vision",
    "multimodal",
    "llava",
    "bakllava",
    "moondream",
    "pixtral",
    "minicpm",
    "internvl",
    "cogvlm",
    "qwen-vl",
    "qwen2-vl",
    "qwen3-vl",
    "qwen3vl",
    # multimodal families whose names don't contain "vision"/"vl" but DO accept
    # images — Gemma 3/4, Llama 4, Mistral Small 3.1/3.2, Phi-4 multimodal
    "gemma-3",
    "gemma3",
    "gemma-4",
    "gemma4",
    "llama-4",
    "llama4",
    "mistral-small-3.1",
    "mistral-small3.1",
    "mistral-small-3.2",
    "mistral-small3.2",
    # Zhipu / GLM vision variants
    "glm-4.5v",
    "glm-4.6v",
    "glm-5v",
    # Qwen3.5 and Qwen3.6 are vision-capable on Ollama but have no "vl" in
    # the tag name — add explicit prefixes so tags like qwen3.5:4b are caught
    "qwen3.5",
    "qwen3.6",
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

    Args:
        model_name: Model tag/name to classify, or ``None``.

    Returns:
        ``True`` if the name heuristically signals native image input,
        ``False`` otherwise.
    """
    m = (model_name or "").lower()

    # Phi-4 naming is ambiguous across backends. Many local tags like `phi4:14b`
    # are text-only; only treat Phi-4 as vision-capable when the tag explicitly
    # signals multimodality.
    if "phi-4" in m or "phi4" in m:
        return any(tok in m for tok in ("vision", "multimodal", "-mm", "_mm")) or bool(
            _VISION_VL_RE.search(m)
        )

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

    Args:
        text: The user's text prompt; becomes the first ``text`` block.
        image_paths: Local filesystem paths to images to attach.

    Returns:
        A multipart content list: one ``text`` block followed by one
        ``image_url`` block per successfully encoded image.
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

        # PDFs must be converted to images before reaching this function.
        # If one slips through (e.g. conversion failed upstream), skip it.
        if ext in _PDF_EXTENSIONS:
            logger.warning(
                "Vision: PDF path reached build_vision_content unconverted: %s — skipping.",
                path,
            )
            content[0]["text"] += f"\n\n[PDF '{Path(path).name}' could not be converted to images]"
            continue

        img_format = _MIME_FROM_EXT.get(ext) or (
            (mimetypes.guess_type(path)[0] or "").split("/")[-1] or "jpeg"
        )

        try:
            with open(path, "rb") as fh:
                encoded = base64.b64encode(fh.read()).decode("utf-8")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/{img_format};base64,{encoded}"},
                }
            )
        except OSError as exc:
            logger.error("Vision: failed to encode image %s: %s", path, exc)
            content[0]["text"] += f"\n\n[Image attached but could not be read: {Path(path).name}]"

    return content


def count_vision_images_in_messages(messages: list[dict[str, Any]]) -> int:
    """Count image_url blocks across all messages (for timeout budgeting).

    Args:
        messages: OpenAI-style chat messages whose ``content`` may be a
            multipart list of blocks.

    Returns:
        The total number of ``image_url`` blocks found across all messages.
    """
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            total += sum(1 for block in content if block.get("type") == "image_url")
    return total


def strip_vision_from_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop image blocks from messages, keeping text only.

    Used before re-attaching images on a follow-up turn so earlier page
    renders are not duplicated in the context window.

    Args:
        messages: OpenAI-style chat messages whose ``content`` may be a
            multipart list of blocks.

    Returns:
        New message dicts with any multipart ``content`` collapsed to the
        joined text of its ``text`` blocks.
    """
    stripped: list[dict[str, Any]] = []
    for msg in messages:
        item = dict(msg)
        content = item.get("content")
        if isinstance(content, list):
            text_parts = [block.get("text", "") for block in content if block.get("type") == "text"]
            item["content"] = " ".join(p for p in text_parts if p).strip() or ""
        stripped.append(item)
    return stripped


# ---------------------------------------------------------------------------
# Image path extraction from free-form text
# ---------------------------------------------------------------------------

_IMG_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
    }
)

# PDF pages are converted to images before being passed to the model.
# Detection uses a separate extension set so build_vision_content (which
# encodes raw bytes) never accidentally receives a .pdf path.
_PDF_EXTENSIONS = frozenset({".pdf"})

_DETECTABLE_EXTENSIONS = _IMG_EXTENSIONS | _PDF_EXTENSIONS

# One pattern that captures image/PDF-looking strings in order of specificity:
#   group 1: double-quoted path  "C:\...\file.ext" or "/path/file.ext"
#   group 2: single-quoted path  'file.ext'
#   group 3: Windows absolute    C:\path\to\file.ext  (unquoted)
#   group 4: Unix absolute       /path/to/file.ext    (unquoted)
#   group 5: bare filename       image1.png / doc.pdf (no separators)
_IMAGE_CANDIDATE_RE = re.compile(
    r'"([^"\r\n]+\.(?:png|jpe?g|webp|gif|bmp|tiff?|pdf))"'
    r"|'([^'\r\n]+\.(?:png|jpe?g|webp|gif|bmp|tiff?|pdf))'"
    r"|([A-Za-z]:[/\\]\S+\.(?:png|jpe?g|webp|gif|bmp|tiff?|pdf))"
    r"|(/\S+\.(?:png|jpe?g|webp|gif|bmp|tiff?|pdf))"
    r"|([\w.\-]+\.(?:png|jpe?g|webp|gif|bmp|tiff?|pdf))",
    re.IGNORECASE,
)


def compute_llm_timeout(num_images: int = 0, *, has_pdf: bool = False) -> float:
    """Return the HTTP timeout (seconds) for an LLM request.

    Vision workloads — especially multi-page PDFs rendered as images — can
    take several minutes before Ollama emits the first token on CPU-bound
    hardware.  The default 300 s ceiling is too short for those cases.

    Args:
        num_images: Number of images attached to the request.
        has_pdf: Whether any attachment originated from a PDF (raises the
            per-image and base budget).

    Returns:
        The HTTP timeout in seconds, capped at 1800.
    """
    if num_images <= 0:
        return 300.0
    per_image = 240.0 if has_pdf else 180.0
    base = 600.0 if has_pdf else 480.0
    return min(1800.0, base + per_image * max(0, num_images - 1))


def pdf_to_images(
    pdf_path: str,
    max_pages: int = 10,
    dpi: int = 96,
) -> tuple[list[Path], Path]:
    """Render a PDF to per-page PNG files and return (page_paths, temp_dir).

    The caller **must** delete ``temp_dir`` after the images are no longer
    needed (use ``shutil.rmtree(temp_dir, ignore_errors=True)``).

    Parameters
    ----------
    pdf_path:
        Absolute path to the PDF file.
    max_pages:
        Maximum number of pages to render (default 10).  Documents longer
        than this are truncated with a log warning.
    dpi:
        Rendering resolution (default 96 dpi).  96 dpi gives ~770×1100 px
        for an A4 page — enough for handwriting OCR while keeping inference
        fast on CPU-bound laptops.  Raise to 150–200 for dense small text.

    Raises
    ------
    ImportError
        If ``pymupdf`` is not installed.
    FileNotFoundError
        If ``pdf_path`` does not exist.
    RuntimeError
        If the PDF cannot be opened (encrypted, corrupt, etc.).
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ImportError(
            "pymupdf is required for PDF support. Install it with:  pip install pymupdf"
        ) from None

    pdf_path = str(pdf_path)
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="ci2lab_pdf_"))
    pages: list[Path] = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"Could not open PDF '{pdf_path}': {exc}") from exc

    try:
        total = len(doc)
        if total > max_pages:
            logger.warning(
                "PDF has %d pages; rendering only the first %d (max_pages=%d).",
                total,
                max_pages,
                max_pages,
            )
        n = min(total, max_pages)
        scale = dpi / 72.0  # PDF base resolution is 72 dpi
        mat = fitz.Matrix(scale, scale)
        for i in range(n):
            page = doc[i]
            pix = page.get_pixmap(matrix=mat)
            out_path = tmp_dir / f"page_{i + 1:03d}.png"
            pix.save(str(out_path))
            pages.append(out_path)
    finally:
        doc.close()

    return pages, tmp_dir


def find_image_candidates(text: str) -> list[str]:
    """Return every image-like string matched by regex, regardless of whether the file exists.

    Used by the REPL to detect filenames the user *intended* as images so it
    can warn when they don't resolve to a real file.

    Args:
        text: Free-form text to scan for image/PDF-looking tokens.

    Returns:
        The matched, whitespace-trimmed candidate strings in order of
        appearance (existence on disk is not checked).
    """
    results: list[str] = []
    for m in _IMAGE_CANDIDATE_RE.finditer(text):
        raw = next(g for g in m.groups() if g is not None)
        raw = raw.strip().rstrip(".,;:!?")
        if raw:
            results.append(raw)
    return results


def extract_image_paths(text: str, cwd: str) -> tuple[str, list[str]]:
    """Scan *text* for image file references, resolve them, and strip them.

    Returns ``(cleaned_prompt, resolved_paths)``.

    Handles all common forms a user might type in the REPL:
      - ``C:\\Users\\clara\\image.png describe this``
      - ``what is in image1.jpg?``
      - ``/home/user/photo.png``
      - Quoted variants: ``"C:\\path with spaces\\img.png"``

    Only paths that **actually exist on disk** are returned — the existence
    check is the primary guard against false positives (e.g. a Python
    variable named ``plot.png`` in text).

    The returned ``cleaned_prompt`` has the matched path tokens removed and
    whitespace normalised.  If removing the paths would leave an empty
    string, the original *text* is kept as the prompt so the model still
    receives something meaningful.

    Args:
        text: The raw user input to scan for image references.
        cwd: Directory used to resolve relative path references.

    Returns:
        A ``(cleaned_prompt, resolved_paths)`` tuple, where
        ``resolved_paths`` are absolute paths to existing image/vision-PDF
        files.
    """
    found: list[str] = []
    spans_to_remove: list[tuple[int, int]] = []
    seen: set[str] = set()

    for m in _IMAGE_CANDIDATE_RE.finditer(text):
        raw = next(g for g in m.groups() if g is not None)
        raw = raw.strip().rstrip(".,;:!?")

        p = Path(raw)
        if not p.is_absolute():
            p = Path(cwd) / raw

        if not p.exists():
            continue

        suffix = p.suffix.lower()
        if suffix == ".pdf":
            if not pdf_needs_vision(p):
                continue
        elif suffix not in _IMG_EXTENSIONS:
            continue

        resolved = str(p.resolve())
        if resolved not in seen:
            seen.add(resolved)
            found.append(resolved)
            spans_to_remove.append((m.start(), m.end()))

    if not spans_to_remove:
        return text, []

    # Remove matched spans from right to left so earlier indices stay valid
    chars = list(text)
    for start, end in sorted(spans_to_remove, reverse=True):
        chars[start:end] = []

    cleaned = " ".join("".join(chars).split()).strip()
    return cleaned or text, found


# ---------------------------------------------------------------------------
# VL fallback analysis
# ---------------------------------------------------------------------------


def analyze_image(
    image_path: str,
    backend_url: str,
    model_tag: str,
    timeout: float = 600.0,
    *,
    prompt: str | None = None,
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
        HTTP timeout in seconds (default 600 — VL inference can be slow).
    prompt:
        Optional user message for the vision model. Defaults to a generic
        description request; pass :data:`ci2lab.harness.vision_exercise.EXERCISE_TRANSCRIPTION_PROMPT`
        for literal exercise transcription.

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
                {"type": "text", "text": prompt or "Describe this image in detail."},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/{img_format};base64,{encoded}"},
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

    except Exception as exc:
        logger.error("Vision analysis failed for %s: %s", image_path, exc)
        return f"[Vision analysis failed: {exc}]"
