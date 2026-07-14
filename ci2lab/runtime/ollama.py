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


def normalize_ollama_model_name(name: str) -> str:
    """Canonicalize Ollama names, treating an omitted tag as ``latest``."""
    normalized = name.strip().lower()
    if not normalized:
        return ""
    leaf = normalized.rsplit("/", 1)[-1]
    return normalized if ":" in leaf else f"{normalized}:latest"


def ollama_model_names_equivalent(left: str, right: str) -> bool:
    """Return whether two names differ only by an omitted ``:latest`` tag."""
    return bool(left.strip() and right.strip()) and (
        normalize_ollama_model_name(left) == normalize_ollama_model_name(right)
    )


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
        if ollama_model_names_equivalent(normalized, tag):
            return True
        if normalized.startswith(f"{tag}-") or normalized.startswith(f"{tag}@"):
            return True
    return False
