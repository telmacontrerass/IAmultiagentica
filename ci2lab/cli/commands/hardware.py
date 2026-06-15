"""Comando hardware."""

from __future__ import annotations

import argparse
import json

from rich.table import Table

from ci2lab.console import console
from ci2lab.contracts import HardwareProfile
from ci2lab.hardware import scan_hardware


def _cmd_hardware(args: argparse.Namespace) -> int:
    profile = scan_hardware()
    if args.json:
        console.print_json(json.dumps(profile.to_dict()))
        return 0

    table = Table(title="Caracteristicas detectadas")
    table.add_column("Dato")
    table.add_column("Valor")
    for key, value in profile.to_dict().items():
        display = str(value)
        if key == "memory_pressure":
            display = "True" if value else "False"
        table.add_row(key, display)
    console.print(table)
    return 0


def _print_memory_budget_context(profile: HardwareProfile) -> None:
    mode = profile.inference_mode
    console.print(
        f"Tu equipo permite teoricamente ~{profile.inference_budget_theoretical_gb:g} GB "
        f"para inferencia en modo {mode}."
    )
    if mode == "gpu" and profile.gpu_vendor != "apple":
        available_label = "VRAM disponible segura ahora"
    else:
        available_label = "RAM disponible segura ahora"
    console.print(
        f"{available_label}: ~{profile.inference_budget_available_gb:g} GB."
    )
    if profile.memory_pressure:
        console.print(
            "[yellow]Aviso: hay presion de memoria. "
            "Cierra aplicaciones antes de usar modelos grandes.[/yellow]"
        )
