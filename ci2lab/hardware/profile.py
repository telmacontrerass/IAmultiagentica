"""Hardware profiling for local model recommendations."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any, Literal

import psutil

from ci2lab.contracts import HardwareProfile, HardwareTier

_CPU_TOTAL_FACTOR = 0.45
_CPU_AVAILABLE_FACTOR = 0.6
_GPU_RESERVE_GB = 2.0
_MEMORY_PRESSURE_RATIO = 0.5


def scan_hardware() -> HardwareProfile:
    """Return a best-effort snapshot of the current machine."""

    memory = psutil.virtual_memory()
    ram_total_gb = _bytes_to_gb(memory.total)
    ram_available_gb = _bytes_to_gb(memory.available)
    os_name = _detect_os()
    cpu_cores = os.cpu_count() or psutil.cpu_count(logical=True) or 1

    gpu = _detect_gpu(os_name=os_name)
    inference_mode = "gpu" if gpu["vram_available_gb"] >= 4 else "cpu"
    if gpu["gpu_vendor"] == "apple" and ram_total_gb >= 8:
        inference_mode = "gpu"

    budgets = _compute_inference_budgets(
        inference_mode=inference_mode,
        gpu_vendor=gpu["gpu_vendor"],
        ram_total_gb=ram_total_gb,
        ram_available_gb=ram_available_gb,
        vram_total_gb=gpu["vram_total_gb"],
        vram_available_gb=gpu["vram_available_gb"],
    )

    hardware_tier = _hardware_tier(
        ram_total_gb=ram_total_gb,
        inference_budget_gb=budgets["inference_budget_gb"],
        inference_mode=inference_mode,
    )

    return HardwareProfile(
        ram_total_gb=ram_total_gb,
        ram_available_gb=ram_available_gb,
        vram_total_gb=gpu["vram_total_gb"],
        vram_available_gb=gpu["vram_available_gb"],
        gpu_name=gpu["gpu_name"],
        gpu_vendor=gpu["gpu_vendor"],
        cpu_cores=cpu_cores,
        os=os_name,
        inference_mode=inference_mode,
        inference_budget_gb=budgets["inference_budget_gb"],
        inference_budget_theoretical_gb=budgets["inference_budget_theoretical_gb"],
        inference_budget_available_gb=budgets["inference_budget_available_gb"],
        memory_pressure=budgets["memory_pressure"],
        hardware_tier=hardware_tier,
        raw=gpu["raw"],
    )


def _compute_inference_budgets(
    *,
    inference_mode: str,
    gpu_vendor: str,
    ram_total_gb: float,
    ram_available_gb: float,
    vram_total_gb: float,
    vram_available_gb: float,
) -> dict[str, float | bool]:
    if inference_mode == "gpu" and gpu_vendor != "apple":
        theoretical = max(0.0, vram_total_gb - _GPU_RESERVE_GB)
        available = max(0.0, vram_available_gb - _GPU_RESERVE_GB)
        budget = available
    else:
        theoretical = max(0.0, ram_total_gb * _CPU_TOTAL_FACTOR)
        available = max(0.0, ram_available_gb * _CPU_AVAILABLE_FACTOR)
        budget = max(0.0, available, theoretical)

    memory_pressure = (
        theoretical > 0.0 and available < theoretical * _MEMORY_PRESSURE_RATIO
    )

    return {
        "inference_budget_theoretical_gb": round(theoretical, 2),
        "inference_budget_available_gb": round(available, 2),
        "inference_budget_gb": round(budget, 2),
        "memory_pressure": memory_pressure,
    }


def build_cpu_profile_for_testing(
    *,
    ram_total_gb: float,
    ram_available_gb: float,
) -> HardwareProfile:
    """Helper for tests: CPU profile without calling psutil."""
    budgets = _compute_inference_budgets(
        inference_mode="cpu",
        gpu_vendor="none",
        ram_total_gb=ram_total_gb,
        ram_available_gb=ram_available_gb,
        vram_total_gb=0.0,
        vram_available_gb=0.0,
    )
    return HardwareProfile(
        ram_total_gb=ram_total_gb,
        ram_available_gb=ram_available_gb,
        vram_total_gb=0.0,
        vram_available_gb=0.0,
        gpu_name="CPU only",
        gpu_vendor="none",
        cpu_cores=8,
        os="windows",
        inference_mode="cpu",
        inference_budget_gb=budgets["inference_budget_gb"],
        inference_budget_theoretical_gb=budgets["inference_budget_theoretical_gb"],
        inference_budget_available_gb=budgets["inference_budget_available_gb"],
        memory_pressure=bool(budgets["memory_pressure"]),
        hardware_tier=_hardware_tier(
            ram_total_gb=ram_total_gb,
            inference_budget_gb=budgets["inference_budget_gb"],
            inference_mode="cpu",
        ),
    )


def _detect_gpu(*, os_name: Literal["windows", "linux", "darwin"]) -> dict[str, Any]:
    nvidia = _detect_nvidia_gpu()
    if nvidia:
        return nvidia

    if os_name == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}:
        chip = _run_command(["sysctl", "-n", "machdep.cpu.brand_string"])
        return {
            "vram_total_gb": 0.0,
            "vram_available_gb": 0.0,
            "gpu_name": chip.strip() or "Apple Silicon GPU",
            "gpu_vendor": "apple",
            "raw": {"apple_silicon": True, "chip": chip.strip()},
        }

    return {
        "vram_total_gb": 0.0,
        "vram_available_gb": 0.0,
        "gpu_name": "CPU only",
        "gpu_vendor": "none",
        "raw": {},
    }


def _detect_nvidia_gpu() -> dict[str, Any] | None:
    if not shutil.which("nvidia-smi"):
        return None

    output = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.free",
            "--format=csv,noheader,nounits",
        ]
    )
    if not output.strip():
        return None

    line = output.strip().splitlines()[0]
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 3:
        return None

    try:
        total_gb = round(float(parts[1]) / 1024, 2)
        free_gb = round(float(parts[2]) / 1024, 2)
    except ValueError:
        return None

    return {
        "vram_total_gb": total_gb,
        "vram_available_gb": free_gb,
        "gpu_name": parts[0],
        "gpu_vendor": "nvidia",
        "raw": {"nvidia_smi": output.strip()},
    }


def _detect_os() -> Literal["windows", "linux", "darwin"]:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "darwin"
    return "linux"


def _hardware_tier(
    *,
    ram_total_gb: float,
    inference_budget_gb: float,
    inference_mode: str,
) -> HardwareTier:
    if inference_budget_gb >= 24 or ram_total_gb >= 64:
        return "enterprise"
    if inference_budget_gb >= 8 or inference_mode == "gpu":
        return "workstation"
    return "edge"


def _bytes_to_gb(value: int) -> float:
    return round(value / (1024**3), 2)


def _run_command(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""
