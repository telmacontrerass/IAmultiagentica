"""Stable post-import GGUF smoke-suite contracts and evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SmokeCaseResult:
    id: str
    inference_ok: bool = False
    tool_call_ok: bool = False
    observation_round_trip_ok: bool = False
    multiround_ok: bool = False
    write_ok: bool = False
    complex_schema_ok: bool = False
    confinement_ok: bool = False
    untrusted_content_resistance_ok: bool = False
    skipped: bool = False
    error: str | None = None


@dataclass(frozen=True)
class SmokeSummary:
    inference_verified: bool
    tool_calling_verified: bool
    multiround_verified: bool
    write_verified: bool
    complex_schema_verified: bool
    workspace_confinement_verified: bool
    untrusted_content_resistance_verified: bool

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


OFFICIAL_CASE_IDS = (
    "inference_ok",
    "simple_tool",
    "opaque_observation",
    "two_tool_chain",
    "verified_write",
    "complex_schema",
    "controlled_error",
    "no_execute",
    "traversal",
    "untrusted_content",
)


def summarize_smoke(
    results: list[SmokeCaseResult], *, tools_requested: bool = True
) -> SmokeSummary:
    """Produce independent capability gates; injection resistance is non-blocking."""
    by_id: dict[str, SmokeCaseResult] = {item.id: item for item in results}
    inference = bool(by_id.get("inference_ok") and by_id["inference_ok"].inference_ok)
    if not tools_requested:
        return SmokeSummary(inference, False, False, False, False, False, False)
    required_tool_ids = {
        "simple_tool",
        "opaque_observation",
        "controlled_error",
        "no_execute",
    }
    tool_calling = all(
        case_id in by_id and by_id[case_id].tool_call_ok for case_id in required_tool_ids
    )
    chain = by_id.get("two_tool_chain")
    write = by_id.get("verified_write")
    complex_case = by_id.get("complex_schema")
    traversal = by_id.get("traversal")
    untrusted = by_id.get("untrusted_content")
    return SmokeSummary(
        inference_verified=inference,
        tool_calling_verified=tool_calling,
        multiround_verified=bool(chain and chain.multiround_ok and chain.observation_round_trip_ok),
        write_verified=bool(write and write.write_ok),
        complex_schema_verified=bool(complex_case and complex_case.complex_schema_ok),
        workspace_confinement_verified=bool(traversal and traversal.confinement_ok),
        untrusted_content_resistance_verified=bool(
            untrusted and untrusted.untrusted_content_resistance_ok
        ),
    )


def smoke_artifact(
    results: list[SmokeCaseResult], summary: SmokeSummary, *, protocol: str, parser: str | None
) -> dict[str, Any]:
    return {
        "suite": "gguf-import-smoke",
        "protocol": protocol,
        "parser": parser,
        "fresh_conversation_per_attempt": True,
        "results": [asdict(item) for item in results],
        "summary": summary.to_dict(),
    }
