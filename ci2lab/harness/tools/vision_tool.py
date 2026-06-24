"""analyze_image agent tool — thin wrapper around ci2lab.harness.vision.

Exposed to the ReAct loop so the agent can call it mid-task with
``{"tool": "analyze_image", "path": "<file>"}`` or with an optional
``"model"`` override.

Resolution order for the vision model tag:
  1. ``model`` argument (explicit override from the LLM call)
  2. ``cfg.vision_model`` (fallback model from AgentConfig / settings.json)
  3. ``cfg.selection.ollama_tag`` — only when the main model is itself
     vision-capable (as determined by ``is_vision_model``).

If no usable vision model can be resolved the tool returns a clear error
string so the agent can continue without crashing.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ci2lab.harness.types import AgentConfig

_QWEN_VL_EXTRACTOR_TAG = "qwen2.5vl:7b"
_SUPPORTED_IMAGE_EXTENSIONS = frozenset({
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
})


def analyze_image_tool(
    image_path: str,
    cfg: AgentConfig,
    model_override: str = "",
) -> str:
    """Analyze a local image file and return a detailed description.

    Parameters
    ----------
    image_path:
        Absolute or workspace-relative path to the image.
    cfg:
        Active AgentConfig — used to resolve the vision model and backend URL.
    model_override:
        Optional Ollama tag that overrides both ``cfg.vision_model`` and
        the main model selection.

    Returns a human-readable description string, never raises.
    """
    from ci2lab.harness.vision import analyze_image, is_vision_model

    if not cfg.vision_enabled:
        return (
            "[Vision is disabled — set vision_enabled: true in "
            "~/.ci2lab/settings.json to enable it]"
        )

    # Resolve the path relative to cwd when not absolute
    resolved = image_path
    if not os.path.isabs(image_path):
        resolved = str(Path(cfg.cwd) / image_path)

    # Resolve vision model tag
    vision_tag = (
        (model_override or "").strip()
        or (cfg.vision_model or "").strip()
        or (
            cfg.selection.ollama_tag
            if cfg.selection and is_vision_model(cfg.selection.ollama_tag)
            else ""
        )
    )

    if not vision_tag:
        return (
            "[Vision: no vision model available — set vision_model in "
            "~/.ci2lab/settings.json or use a vision-capable main model]"
        )

    backend_url = (
        cfg.selection.backend_url
        if cfg.selection
        else "http://localhost:11434/v1"
    )

    return analyze_image(resolved, backend_url, vision_tag)


def extract_visual_document_tool(
    document_path: str,
    cfg: AgentConfig,
) -> str:
    """Extract handwritten/visual document content with a fixed VL model.

    This tool is extraction-only: it transcribes what appears on images/PDF pages
    and leaves correctness checks to the main reasoning model.
    """
    from ci2lab.harness.tools.filesystem_parts.documents import pdf_needs_vision
    from ci2lab.harness.vision import analyze_image, compute_llm_timeout, pdf_to_images

    if not cfg.vision_enabled:
        return (
            "[Vision is disabled — set vision_enabled: true in "
            "~/.ci2lab/settings.json to enable it]"
        )

    resolved = document_path
    if not os.path.isabs(document_path):
        resolved = str(Path(cfg.cwd) / document_path)
    path = Path(resolved)

    if not path.exists():
        return f"[Document not found: {resolved}]"

    backend_url = (
        cfg.selection.backend_url
        if cfg.selection
        else "http://localhost:11434/v1"
    )
    vision_tag = _QWEN_VL_EXTRACTOR_TAG

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        if not pdf_needs_vision(path):
            return (
                "[PDF appears text-based; use read_document for direct text extraction. "
                "extract_visual_document is intended for scanned/handwritten content.]"
            )

        temp_dir: Path | None = None
        try:
            page_paths, temp_dir = pdf_to_images(str(path))
            if not page_paths:
                return f"[No pages rendered from PDF: {path.name}]"
            timeout = compute_llm_timeout(len(page_paths), has_pdf=True)
            out: list[str] = [
                f"Document: {path.name}",
                f"Extractor model: {vision_tag}",
                "Instruction: extraction only (no correctness judgment).",
            ]
            for idx, page in enumerate(page_paths, start=1):
                desc = analyze_image(
                    str(page),
                    backend_url,
                    vision_tag,
                    timeout=timeout,
                )
                out.append(f"[Page {idx}]\n{desc}")
            return "\n\n".join(out)
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    if suffix in _SUPPORTED_IMAGE_EXTENSIONS:
        timeout = compute_llm_timeout(1, has_pdf=False)
        desc = analyze_image(str(path), backend_url, vision_tag, timeout=timeout)
        return "\n\n".join([
            f"Document: {path.name}",
            f"Extractor model: {vision_tag}",
            "Instruction: extraction only (no correctness judgment).",
            f"[Image 1]\n{desc}",
        ])

    return (
        "[Unsupported file type for extract_visual_document. "
        "Supported: PDF, JPG, JPEG, PNG, GIF, WEBP, BMP, TIFF, TIF.]"
    )
