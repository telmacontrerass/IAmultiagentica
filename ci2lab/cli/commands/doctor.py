"""Comando doctor."""

from __future__ import annotations

import importlib.util
import shutil

from ci2lab.console import console
from ci2lab.config import Ci2LabConfig

# Marcadores ASCII para salida compatible con consolas Windows (cp1252).
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
    import httpx

    ok = True
    console.print("[bold]ci2lab doctor[/bold]\n")

    try:
        import ci2lab  # noqa: F401

        console.print(f"[green]{_DOCTOR_OK}[/green] Paquete ci2lab importable")
    except ImportError as exc:
        console.print(f"[red]{_DOCTOR_ERROR}[/red] ci2lab: {exc}")
        ok = False

    missing_document_deps = _missing_document_dependencies()
    if missing_document_deps:
        names = ", ".join(name for name, _label in missing_document_deps)
        console.print(
            f"[yellow]{_DOCTOR_WARN}[/yellow] Faltan librerias de documentos: {names}"
        )
        console.print('  Ejecuta: pip install -e ".[dev]"')
    else:
        labels = ", ".join(label for _name, label in _DOCUMENT_DEPENDENCIES)
        console.print(
            f"[green]{_DOCTOR_OK}[/green] Lectura de documentos disponible ({labels})"
        )

    if shutil.which("pandoc"):
        console.print(f"[green]{_DOCTOR_OK}[/green] pandoc disponible en PATH")
    else:
        console.print(
            f"[yellow]{_DOCTOR_WARN}[/yellow] pandoc no encontrado en PATH"
            " (necesario para write_docx y docx_to_pdf)"
        )
        console.print("  Instálalo con: winget install JohnMacFarlane.Pandoc")

    base_url = runtime.backend_url.removesuffix("/v1").rstrip("/")
    try:
        r = httpx.get(f"{base_url}/api/tags", timeout=3.0)
        r.raise_for_status()
        models = [m.get("name") for m in r.json().get("models", [])]
        console.print(
            f"[green]{_DOCTOR_OK}[/green] Ollama en {base_url} ({len(models)} modelos)"
        )
        if models:
            console.print(f"  Ejemplos: {', '.join(models[:5])}")
        if runtime.model not in models and not any(
            m and m.startswith(runtime.model.split(":")[0]) for m in models
        ):
            console.print(
                f"[yellow]{_DOCTOR_WARN}[/yellow] Modelo configurado "
                f"`{runtime.model}` no aparece en la lista"
            )
    except Exception as exc:
        console.print(
            f"[yellow]{_DOCTOR_WARN}[/yellow] Ollama no responde en {base_url}: {exc}"
        )
        console.print("  Comprueba que Ollama esté abierto y que `ollama serve` esté corriendo.")

    return 0 if ok else 1


def _missing_document_dependencies() -> list[tuple[str, str]]:
    return [
        (module_name, label)
        for module_name, label in _DOCUMENT_DEPENDENCIES
        if importlib.util.find_spec(module_name) is None
    ]
