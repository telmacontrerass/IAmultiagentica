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
from pathlib import Path

from ci2lab.harness.types import AgentConfig


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
