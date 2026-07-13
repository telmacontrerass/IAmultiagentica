"""doctor command."""

from __future__ import annotations

import importlib.util
import shutil
from typing import Any

from ci2lab.config import Ci2LabConfig
from ci2lab.console import console

# ASCII markers for output compatible with Windows consoles (cp1252).
_DOCTOR_OK = "OK"
_DOCTOR_ERROR = "ERROR"
_DOCTOR_WARN = "WARN"

_DOCUMENT_DEPENDENCIES = (
    ("pypdf", "PDF"),
    ("docx", "Word/DOCX"),
    ("pptx", "PowerPoint/PPTX"),
    ("openpyxl", "Excel/XLSX"),
    ("pdf2docx", "PDF a DOCX"),
)

_BACKEND_TIMEOUT_SECONDS = 3.0
_BACKEND_CONNECT_TIMEOUT_SECONDS = 1.0


def _cmd_doctor(runtime: Ci2LabConfig) -> int:
    """Check the environment and the configured inference backend.

    Args:
        runtime: The merged runtime configuration, used for the backend URL and
            the configured model name.

    Returns:
        Process exit code: ``0`` if the core package imports, ``1`` otherwise.
        Missing optional dependencies and an unreachable backend are reported
        as warnings and do not change the exit code.
    """
    ok = True
    console.print("[bold]ci2lab doctor[/bold]\n")

    try:
        import ci2lab  # noqa: F401

        console.print(f"[green]{_DOCTOR_OK}[/green] ci2lab package importable")
    except ImportError as exc:
        console.print(f"[red]{_DOCTOR_ERROR}[/red] ci2lab: {exc}")
        ok = False

    missing_document_deps = _missing_document_dependencies()
    if missing_document_deps:
        names = ", ".join(name for name, _label in missing_document_deps)
        console.print(f"[yellow]{_DOCTOR_WARN}[/yellow] Missing document libraries: {names}")
        console.print('  Run: pip install -e ".[dev]"')
    else:
        labels = ", ".join(label for _name, label in _DOCUMENT_DEPENDENCIES)
        console.print(f"[green]{_DOCTOR_OK}[/green] Document reading available ({labels})")

    if shutil.which("pandoc"):
        console.print(f"[green]{_DOCTOR_OK}[/green] pandoc available on PATH")
    else:
        console.print(
            f"[yellow]{_DOCTOR_WARN}[/yellow] pandoc not found on PATH"
            " (required for write_docx and docx_to_pdf)"
        )
        console.print("  Install it with: winget install JohnMacFarlane.Pandoc")

    try:
        if runtime.backend == "ollama":
            _check_ollama_backend(runtime)
        else:
            _check_openai_backend(runtime)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130

    return 0 if ok else 1


def _check_ollama_backend(runtime: Ci2LabConfig) -> None:
    """Check an Ollama server through its native model-list endpoint."""
    import httpx

    base_url = runtime.backend_url.removesuffix("/v1").rstrip("/")
    try:
        r = httpx.get(
            f"{base_url}/api/tags",
            timeout=_backend_timeout(),
            trust_env=False,
        )
        r.raise_for_status()
        models = [m.get("name") for m in r.json().get("models", [])]
        console.print(f"[green]{_DOCTOR_OK}[/green] Ollama at {base_url} ({len(models)} models)")
        if models:
            console.print(f"  Examples: {', '.join(models[:5])}")
        if runtime.model not in models and not any(
            m and m.startswith(runtime.model.split(":")[0]) for m in models
        ):
            console.print(
                f"[yellow]{_DOCTOR_WARN}[/yellow] Configured model "
                f"`{runtime.model}` does not appear in the list"
            )
    except Exception as exc:
        console.print(f"[yellow]{_DOCTOR_WARN}[/yellow] Ollama not responding at {base_url}: {exc}")
        console.print("  Check that Ollama is open and that `ollama serve` is running.")


def _check_openai_backend(runtime: Ci2LabConfig) -> None:
    """Check an OpenAI-compatible chat-completions server."""
    import httpx

    base_url = runtime.backend_url.rstrip("/")
    models_url = f"{base_url}/models"
    chat_url = f"{base_url}/chat/completions"
    try:
        models_response = httpx.get(
            models_url,
            timeout=_backend_timeout(),
            trust_env=False,
        )
        models_response.raise_for_status()
        models = _openai_model_names(models_response.json())
        console.print(
            f"[green]{_DOCTOR_OK}[/green] OpenAI-compatible backend at "
            f"{base_url} ({len(models)} models)"
        )
        if models:
            console.print(f"  Examples: {', '.join(models[:5])}")
            if runtime.model not in models:
                console.print(
                    f"[yellow]{_DOCTOR_WARN}[/yellow] Configured model "
                    f"`{runtime.model}` does not appear in /models"
                )
        return
    except Exception as models_exc:
        try:
            payload = {
                "model": runtime.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
                "stream": False,
            }
            chat_response = httpx.post(
                chat_url,
                json=payload,
                timeout=_backend_timeout(),
                trust_env=False,
            )
            chat_response.raise_for_status()
            console.print(
                f"[green]{_DOCTOR_OK}[/green] OpenAI-compatible chat endpoint at {chat_url}"
            )
            console.print("[dim]Note: /models was unavailable, but chat/completions responded.[/dim]")
        except Exception as chat_exc:
            console.print(
                f"[yellow]{_DOCTOR_WARN}[/yellow] OpenAI-compatible backend "
                f"not responding at {base_url}"
            )
            console.print(f"  /models error: {models_exc}")
            console.print(f"  /chat/completions error: {chat_exc}")
            console.print("  Check the local server, base URL, model name, and /v1/chat/completions.")


def _openai_model_names(payload: dict[str, Any]) -> list[str]:
    """Extract model ids from an OpenAI-compatible /models response."""
    raw = payload.get("data") or payload.get("models") or []
    names: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = item.get("id") or item.get("name")
                if name:
                    names.append(str(name))
            elif isinstance(item, str):
                names.append(item)
    return names


def _backend_timeout() -> Any:
    """Return a short backend timeout without importing httpx at module import."""
    import httpx

    return httpx.Timeout(
        _BACKEND_TIMEOUT_SECONDS,
        connect=_BACKEND_CONNECT_TIMEOUT_SECONDS,
    )


def _missing_document_dependencies() -> list[tuple[str, str]]:
    """Return the ``(module, label)`` pairs whose import module is not installed."""
    return [
        (module_name, label)
        for module_name, label in _DOCUMENT_DEPENDENCIES
        if importlib.util.find_spec(module_name) is None
    ]
