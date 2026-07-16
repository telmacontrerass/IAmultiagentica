"""Helpers for querying the local Ollama runtime."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import httpx

from ci2lab.config import DEFAULT_BACKEND_URL


def ollama_base_url(backend_url: str) -> str:
    """Return the Ollama base URL, stripping a trailing ``/v1`` and slashes.

    Args:
        backend_url: The configured backend URL, which may point at the
            OpenAI-compatible ``/v1`` endpoint.

    Returns:
        The native Ollama base URL (e.g. ``http://127.0.0.1:11434``).
    """
    return backend_url.removesuffix("/v1").rstrip("/")


def ollama_install_info() -> dict[str, str | None]:
    """Best-effort local paths for the Ollama executable and model store."""
    executable = shutil.which("ollama")
    if executable is None:
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Ollama" / "ollama.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                executable = str(candidate)
                break

    configured_models = os.environ.get("OLLAMA_MODELS")
    if configured_models:
        models_dir = configured_models
    else:
        models_dir = str(Path.home() / ".ollama" / "models")

    return {
        "executable": executable,
        "models_dir": models_dir,
    }


def fetch_installed_models(
    backend_url: str = DEFAULT_BACKEND_URL,
    *,
    timeout: float = 3.0,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch the locally installed models from the Ollama ``/api/tags`` endpoint.

    Args:
        backend_url: Backend URL to query (the ``/v1`` suffix is stripped).
        timeout: Per-request timeout in seconds.

    Returns:
        A tuple ``(models, error)``. ``models`` is a list of dicts with
        ``name``/``size``/``modified_at`` keys; on failure it is empty and
        ``error`` holds the exception message. ``error`` is ``None`` on success.
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{ollama_base_url(backend_url)}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
            return [
                {
                    "name": model.get("name", ""),
                    "size": model.get("size"),
                    "modified_at": model.get("modified_at"),
                }
                for model in models
            ], None
    except Exception as exc:
        return [], str(exc)


def fetch_installed_model_names(
    backend_url: str = DEFAULT_BACKEND_URL,
    *,
    timeout: float = 3.0,
) -> tuple[set[str], str | None]:
    """Fetch just the set of installed model names.

    Args:
        backend_url: Backend URL to query (the ``/v1`` suffix is stripped).
        timeout: Per-request timeout in seconds.

    Returns:
        A tuple ``(names, error)`` where ``names`` is the set of installed model
        names and ``error`` is ``None`` on success or the message on failure.
    """
    installed, error = fetch_installed_models(backend_url, timeout=timeout)
    return {item["name"] for item in installed if item.get("name")}, error


def pick_installed_model(installed_names: set[str]) -> str | None:
    """Pick a sensible default from the locally installed Ollama models.

    Prefers instruction-tuned / tool-capable tags (their names usually carry an
    ``instruct`` or ``tool`` marker) and otherwise falls back to the first name
    in a stable alphabetical order so the choice is deterministic.

    Args:
        installed_names: The set of locally installed model names.

    Returns:
        A model name to use, or ``None`` when nothing is installed.
    """
    names = sorted(n for n in installed_names if n)
    if not names:
        return None
    preferred = [n for n in names if "instruct" in n.lower() or "tool" in n.lower()]
    return (preferred or names)[0]


def _installed_match(requested: str, installed_names: set[str]) -> str | None:
    """Return the concrete installed name that ``requested`` refers to, if any.

    Matches an exact name as well as a quantization/variant suffix (e.g.
    ``qwen2.5:3b`` -> the installed ``qwen2.5:3b-instruct``), so a slightly
    imprecise tag still maps to the model that is really on disk.
    """
    tag = requested.strip().lower()
    if not tag:
        return None
    exact = [n for n in installed_names if n.strip().lower() == tag]
    if exact:
        return exact[0]
    variants = sorted(
        n
        for n in installed_names
        if n.strip().lower().startswith(f"{tag}-") or n.strip().lower().startswith(f"{tag}@")
    )
    return variants[0] if variants else None


def resolve_ollama_model(
    requested: str,
    backend_url: str = DEFAULT_BACKEND_URL,
    *,
    allow_fallback: bool = False,
    timeout: float = 3.0,
) -> str:
    """Resolve ``requested`` against the models actually installed on Ollama.

    Resolution order:

    1. If ``requested`` matches an installed model (exactly or as a
       quantization/variant suffix), the concrete installed name is returned so
       the request targets a model that is really present.
    2. Otherwise, when ``allow_fallback`` is set (used only when no model was
       explicitly chosen), an installed model is auto-selected.
    3. Failing both — or when the server is unreachable — ``requested`` is
       returned unchanged.

    Args:
        requested: The model tag from configuration, env, or CLI.
        backend_url: Backend URL to query (the ``/v1`` suffix is stripped).
        allow_fallback: When ``True``, substitute an installed model if
            ``requested`` is not installed at all.
        timeout: Per-request timeout in seconds.

    Returns:
        A model tag to use for the session.
    """
    installed, error = fetch_installed_model_names(backend_url, timeout=timeout)
    if error is not None or not installed:
        return requested
    match = _installed_match(requested, installed)
    if match is not None:
        return match
    if allow_fallback:
        return pick_installed_model(installed) or requested
    return requested


def is_catalog_model_installed(ollama_tag: str, installed_names: set[str]) -> bool:
    """Return True if a catalog tag matches any installed model name.

    Matches an exact tag as well as installed names that extend the tag with a
    quantization suffix (``tag-...``) or a digest (``tag@...``).

    Args:
        ollama_tag: The catalog model's Ollama tag.
        installed_names: The set of locally installed model names.

    Returns:
        ``True`` when an installed name corresponds to ``ollama_tag``.
    """
    tag = ollama_tag.strip().lower()
    if not tag:
        return False
    for name in installed_names:
        normalized = name.strip().lower()
        if normalized == tag:
            return True
        if normalized.startswith(f"{tag}-") or normalized.startswith(f"{tag}@"):
            return True
    return False
