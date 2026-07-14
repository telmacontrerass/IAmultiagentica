"""Serializable, evidence-based capabilities for imported GGUF models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, cast

ToolProtocol = Literal["native", "adapted_native", "fenced", "unavailable", "unverified"]
ImportState = Literal[
    "IMPORTED_AND_VERIFIED",
    "IMPORTED_TOOLS_VERIFIED",
    "IMPORTED_INFERENCE_ONLY",
    "IMPORT_FAILED",
    "IMPORT_PARTIALLY_COMPLETED",
]


@dataclass(frozen=True)
class InferenceCapability:
    verified: bool = False
    backend: str = "ollama"
    context_length: int | None = None


@dataclass(frozen=True)
class ToolCallingCapability:
    verified: bool = False
    protocol: ToolProtocol = "unverified"
    parser: str | None = None
    adapter: str | None = None
    template_source: str = "unknown"
    selection_reason: str = "not empirically verified"
    evidence_level: Literal["default", "configured", "detected", "verified"] = "default"


@dataclass(frozen=True)
class SecurityCapability:
    workspace_confinement_verified: bool = False
    untrusted_content_resistance_verified: bool = False


@dataclass(frozen=True)
class ImportedCapabilities:
    inference: InferenceCapability = field(default_factory=InferenceCapability)
    tool_calling: ToolCallingCapability = field(default_factory=ToolCallingCapability)
    security: SecurityCapability = field(default_factory=SecurityCapability)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> ImportedCapabilities:
        data = value if isinstance(value, dict) else {}
        inference = cast(
            dict[str, Any], data.get("inference") if isinstance(data.get("inference"), dict) else {}
        )
        tools = cast(
            dict[str, Any],
            data.get("tool_calling") if isinstance(data.get("tool_calling"), dict) else {},
        )
        security = cast(
            dict[str, Any], data.get("security") if isinstance(data.get("security"), dict) else {}
        )
        return cls(
            inference=InferenceCapability(
                verified=bool(inference.get("verified", False)),
                backend=str(inference.get("backend") or "ollama"),
                context_length=(
                    int(inference["context_length"])
                    if inference.get("context_length") is not None
                    else None
                ),
            ),
            tool_calling=ToolCallingCapability(
                verified=bool(tools.get("verified", False)),
                protocol=_protocol(tools.get("protocol")),
                parser=str(tools["parser"]) if tools.get("parser") is not None else None,
                adapter=str(tools["adapter"]) if tools.get("adapter") is not None else None,
                template_source=str(tools.get("template_source") or "unknown"),
                selection_reason=str(tools.get("selection_reason") or "not empirically verified"),
                evidence_level=_evidence_level(tools.get("evidence_level")),
            ),
            security=SecurityCapability(
                workspace_confinement_verified=bool(
                    security.get("workspace_confinement_verified", False)
                ),
                untrusted_content_resistance_verified=bool(
                    security.get("untrusted_content_resistance_verified", False)
                ),
            ),
        )


def _protocol(value: object) -> ToolProtocol:
    text = str(value or "unverified")
    return text if text in {"native", "adapted_native", "fenced", "unavailable"} else "unverified"  # type: ignore[return-value]


def _evidence_level(value: object) -> Literal["default", "configured", "detected", "verified"]:
    text = str(value or "default")
    return text if text in {"default", "configured", "detected", "verified"} else "default"  # type: ignore[return-value]
