"""doctor command."""

from __future__ import annotations

import importlib.util
import shutil

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


def _cmd_doctor(runtime: Ci2LabConfig) -> int:
    """Check the environment: package import, document libs, pandoc and Ollama.

    Args:
        runtime: The merged runtime configuration, used for the backend URL and
            the configured model name.

    Returns:
        Process exit code: ``0`` if the core package imports, ``1`` otherwise.
        Missing optional dependencies and an unreachable Ollama are reported as
        warnings and do not change the exit code.
    """
    import httpx

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

    base_url = runtime.backend_url.removesuffix("/v1").rstrip("/")
    try:
        r = httpx.get(f"{base_url}/api/tags", timeout=3.0)
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

    return 0 if ok else 1


def _missing_document_dependencies() -> list[tuple[str, str]]:
    """Return the ``(module, label)`` pairs whose import module is not installed."""
    return [
        (module_name, label)
        for module_name, label in _DOCUMENT_DEPENDENCIES
        if importlib.util.find_spec(module_name) is None
    ]
