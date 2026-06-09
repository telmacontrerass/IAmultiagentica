"""
Contrato de integración Ci2Lab — COMPARTIDO entre router y arnés.

⚠️  No romper compatibilidad sin acuerdo entre ambas partes.
    Campos nuevos: solo como opcionales con default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

IntentCategory = Literal[
    "coding",
    "rag",
    "reasoning",
    "translation",
    "vision",
    "voice",
    "edge",
    "general",
]

HardwareTier = Literal["edge", "workstation", "enterprise"]

InferenceMode = Literal["cpu", "gpu"]

ToolMode = Literal["native", "fenced"]


@dataclass
class HardwareProfile:
    """Foto del sistema en el momento del escaneo."""

    ram_total_gb: float
    ram_available_gb: float
    vram_total_gb: float
    vram_available_gb: float
    gpu_name: str
    gpu_vendor: Literal["nvidia", "amd", "intel", "apple", "none"]
    cpu_cores: int
    os: Literal["windows", "linux", "darwin"]
    inference_mode: InferenceMode
    """gpu si hay VRAM utilizable (≥4 GB); si no, cpu."""

    inference_budget_gb: float
    """VRAM o RAM disponible para cargar el modelo, ya con margen de seguridad."""

    hardware_tier: HardwareTier = "workstation"
    """edge | workstation | enterprise — calculado por el profiler o router."""

    raw: dict[str, Any] = field(default_factory=dict)
    """Datos extra del escaneo (ej. salida nvidia-smi) para debug."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ram_total_gb": self.ram_total_gb,
            "ram_available_gb": self.ram_available_gb,
            "vram_total_gb": self.vram_total_gb,
            "vram_available_gb": self.vram_available_gb,
            "gpu_name": self.gpu_name,
            "gpu_vendor": self.gpu_vendor,
            "cpu_cores": self.cpu_cores,
            "os": self.os,
            "inference_mode": self.inference_mode,
            "inference_budget_gb": self.inference_budget_gb,
            "hardware_tier": self.hardware_tier,
        }


@dataclass
class IntentResult:
    """Salida del clasificador de intención (router)."""

    category: IntentCategory
    confidence: float
    signals: list[str] = field(default_factory=list)
    difficulty: Literal["low", "medium", "high"] = "medium"


@dataclass
class ModelSpec:
    """Entrada de catálogo — referencia; el router la carga desde models.json."""

    id: str
    display_name: str
    family: str
    categories: list[str]
    ollama_tag: str
    vram_min_gb: float
    ram_inference_gb: float
    supports_tools: bool
    tool_mode: ToolMode
    context_length: int
    tier: HardwareTier
    benchmark_score: dict[str, float] = field(default_factory=dict)


@dataclass
class ModelAlternative:
    model_id: str
    ollama_tag: str
    reason: str


@dataclass
class ModelSelection:
    """
    Salida del router → entrada del arnés.

    El arnés debe poder arrancar solo con este objeto (+ user_prompt).
    """

    model_id: str
    ollama_tag: str
    display_name: str

    backend: Literal["ollama"] = "ollama"
    backend_url: str = "http://localhost:11434/v1"

    tool_mode: ToolMode = "native"
    supports_tools: bool = True
    context_length: int = 8192
    max_tokens: int = 4096
    temperature: float = 0.2

    intent: IntentResult | None = None
    hardware_tier: HardwareTier = "workstation"

    reason: str = ""
    alternatives: list[ModelAlternative] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "ollama_tag": self.ollama_tag,
            "display_name": self.display_name,
            "backend": self.backend,
            "backend_url": self.backend_url,
            "tool_mode": self.tool_mode,
            "supports_tools": self.supports_tools,
            "context_length": self.context_length,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "intent": {
                "category": self.intent.category,
                "confidence": self.intent.confidence,
                "signals": self.intent.signals,
                "difficulty": self.intent.difficulty,
            }
            if self.intent
            else None,
            "hardware_tier": self.hardware_tier,
            "reason": self.reason,
            "alternatives": [
                {"model_id": a.model_id, "ollama_tag": a.ollama_tag, "reason": a.reason}
                for a in self.alternatives
            ],
            "warnings": self.warnings,
        }
