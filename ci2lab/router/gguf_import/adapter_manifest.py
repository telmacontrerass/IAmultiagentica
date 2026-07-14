"""Serializable declarations for opt-in GGUF protocol adapters."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

CATALOG_PATH = Path(__file__).resolve().parents[2] / "catalog" / "experimental_gguf_adapters.json"
AdapterStatus = Literal["experimental", "verified", "deprecated"]
AdaptedToolMode = Literal["adapted_native"]


@dataclass(frozen=True)
class AdapterMatch:
    architecture: str
    original_template_sha256: str
    runtime: str


@dataclass(frozen=True)
class TransformSpec:
    type: str
    anchor: str
    expected_adapted_template_sha256: str
    message: dict[str, str]
    position: str


@dataclass(frozen=True)
class ToolCallSpec:
    encoding: str
    name_source: str
    arguments_source: str
    leading_text_policy: str
    trailing_text_policy: str
    multiple_json_policy: str


@dataclass(frozen=True)
class ReinjectionSpec:
    call_message: dict[str, str]
    result_message: dict[str, str]


@dataclass(frozen=True)
class AdapterValidation:
    tested_runtime: str
    minimum_runtime: str
    validated_at: str
    scenarios_passed: tuple[str, ...]


@dataclass(frozen=True)
class GGUFAdapterManifest:
    id: str
    version: int
    status: AdapterStatus
    enabled: bool
    origin: str
    match: AdapterMatch
    transform: TransformSpec
    tool_call: ToolCallSpec
    reinjection: ReinjectionSpec
    validation: AdapterValidation
    adapted_tool_mode: AdaptedToolMode
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> GGUFAdapterManifest:
        template = item["template"]
        return cls(
            id=str(item["id"]),
            version=int(item["version"]),
            status=item["status"],
            enabled=bool(item["enabled"]),
            origin=str(item["origin"]),
            match=AdapterMatch(**item["match"]),
            transform=TransformSpec(**template["transform"]),
            tool_call=ToolCallSpec(**item["tool_call"]),
            reinjection=ReinjectionSpec(**item["reinjection"]),
            validation=AdapterValidation(
                **{
                    **item["validation"],
                    "scenarios_passed": tuple(item["validation"]["scenarios_passed"]),
                }
            ),
            adapted_tool_mode=item["adapted_tool_mode"],
            limitations=tuple(item.get("limitations", [])),
        )

    def matches(self, *, architecture: str, template_sha256: str, runtime: str) -> bool:
        return self.enabled and (
            architecture,
            template_sha256,
            runtime,
        ) == (
            self.match.architecture,
            self.match.original_template_sha256,
            self.match.runtime,
        )

    def runtime_version_compatible(self, reported: str) -> bool:
        minimum = re.search(r"\d+", self.validation.minimum_runtime)
        actual = re.search(r"(?:version:\s*)?(\d+)", reported)
        return bool(minimum and actual and int(actual.group(1)) >= int(minimum.group()))


def load_adapter_catalog(path: Path = CATALOG_PATH) -> tuple[GGUFAdapterManifest, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported experimental adapter catalog version")
    return tuple(GGUFAdapterManifest.from_dict(item) for item in payload["adapters"])


def get_adapter(adapter_id: str, path: Path = CATALOG_PATH) -> GGUFAdapterManifest:
    matches = [item for item in load_adapter_catalog(path) if item.id == adapter_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one experimental adapter named {adapter_id!r}")
    return matches[0]
