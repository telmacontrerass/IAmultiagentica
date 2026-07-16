from ci2lab.router.gguf_import.capabilities import ImportedCapabilities
from ci2lab.router.gguf_import.protocol import ProtocolEvidence, select_tool_protocol
from ci2lab.router.gguf_import.smoke import SmokeCaseResult, summarize_smoke


def test_capabilities_default_to_unverified_and_round_trip():
    default = ImportedCapabilities()
    loaded = ImportedCapabilities.from_dict(default.to_dict())
    assert loaded == default
    assert not loaded.inference.verified
    assert not loaded.tool_calling.verified
    assert loaded.tool_calling.protocol == "unverified"


def test_protocol_policy_precedence_and_no_fallback_promotion():
    native = select_tool_protocol(ProtocolEvidence(True, "adapter", True, True, "gguf_embedded"))
    adapted = select_tool_protocol(ProtocolEvidence(False, "adapter", True, True))
    fenced = select_tool_protocol(ProtocolEvidence(fenced_enabled=True))
    unavailable = select_tool_protocol(ProtocolEvidence())
    assert (native.protocol, native.parser, native.verified) == (
        "native",
        "openai_tool_calls",
        True,
    )
    assert (adapted.protocol, adapted.adapter, adapted.verified) == (
        "adapted_native",
        "adapter",
        True,
    )
    assert fenced.protocol == "fenced" and not fenced.verified
    assert unavailable.protocol == "unavailable" and not unavailable.verified


def test_smoke_security_is_independent_from_technical_tool_verification():
    results = [
        SmokeCaseResult("inference_ok", inference_ok=True),
        SmokeCaseResult("simple_tool", tool_call_ok=True),
        SmokeCaseResult("opaque_observation", tool_call_ok=True),
        SmokeCaseResult("controlled_error", tool_call_ok=True),
        SmokeCaseResult("no_execute", tool_call_ok=True),
        SmokeCaseResult("two_tool_chain", multiround_ok=True, observation_round_trip_ok=True),
        SmokeCaseResult("verified_write", write_ok=True),
        SmokeCaseResult("complex_schema", complex_schema_ok=True),
        SmokeCaseResult("traversal", confinement_ok=True),
        SmokeCaseResult("untrusted_content", untrusted_content_resistance_ok=False),
    ]
    summary = summarize_smoke(results)
    assert summary.inference_verified
    assert summary.tool_calling_verified
    assert summary.multiround_verified
    assert summary.workspace_confinement_verified
    assert not summary.untrusted_content_resistance_verified
