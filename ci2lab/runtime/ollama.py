"""Helpers for querying the local Ollama runtime."""

from __future__ import annotations

import os
import shutil
from typing import Any
from pathlib import Path

import httpx

from ci2lab.config import DEFAULT_BACKEND_URL


def ollama_base_url(backend_url: str) -> str:
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
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)


def fetch_installed_model_names(
    backend_url: str = DEFAULT_BACKEND_URL,
    *,
    timeout: float = 3.0,
) -> tuple[set[str], str | None]:
    installed, error = fetch_installed_models(backend_url, timeout=timeout)
    return {item["name"] for item in installed if item.get("name")}, error


def is_catalog_model_installed(ollama_tag: str, installed_names: set[str]) -> bool:
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
