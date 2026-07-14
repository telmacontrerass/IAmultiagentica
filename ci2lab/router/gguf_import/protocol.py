"""Single policy for choosing an imported GGUF tool protocol."""

from __future__ import annotations

from dataclasses import dataclass

from ci2lab.router.gguf_import.capabilities import ToolCallingCapability


@dataclass(frozen=True)
class ProtocolEvidence:
    native_tool_calls_valid: bool = False
    adapter_id: str | None = None
    adapter_verified: bool = False
    fenced_enabled: bool = False
    template_source: str = "unknown"


def select_tool_protocol(evidence: ProtocolEvidence) -> ToolCallingCapability:
    """Apply the documented precedence without promoting configured fallbacks."""
    if evidence.native_tool_calls_valid:
        return ToolCallingCapability(
            verified=True,
            protocol="native",
            parser="openai_tool_calls",
            template_source=evidence.template_source,
            selection_reason="backend returned a valid structured tool_calls response",
            evidence_level="verified",
        )
    if evidence.adapter_id and evidence.adapter_verified:
        return ToolCallingCapability(
            verified=True,
            protocol="adapted_native",
            parser=evidence.adapter_id,
            adapter=evidence.adapter_id,
            template_source="family_adapter",
            selection_reason="family adapter completed empirical tool validation",
            evidence_level="verified",
        )
    if evidence.fenced_enabled:
        return ToolCallingCapability(
            protocol="fenced",
            parser="fenced_v1",
            template_source=evidence.template_source,
            selection_reason="experimental fenced fallback configured but not verified",
            evidence_level="configured",
        )
    return ToolCallingCapability(
        protocol="unavailable",
        selection_reason="no valid native call, verified adapter, or enabled fallback",
        evidence_level="detected",
    )
