"""hardware command."""

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

    table = Table(title="Detected characteristics")
    table.add_column("Field")
    table.add_column("Value")
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
        f"Your machine theoretically allows ~{profile.inference_budget_theoretical_gb:g} GB "
        f"for inference in {mode} mode."
    )
    if mode == "gpu" and profile.gpu_vendor != "apple":
        available_label = "Safe VRAM available now"
    else:
        available_label = "Safe RAM available now"
    console.print(
        f"{available_label}: ~{profile.inference_budget_available_gb:g} GB."
    )
    if profile.memory_pressure:
        console.print(
            "[yellow]Warning: there is memory pressure. "
            "Close applications before using large models.[/yellow]"
        )
