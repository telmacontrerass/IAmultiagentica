"""Manifest-driven conversion of textual model protocols to canonical tool calls."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from ci2lab.router.gguf_import.adapter_manifest import GGUFAdapterManifest

Confidence = Literal["exact", "rejected"]


@dataclass(frozen=True)
class NormalizedToolCall:
    name: str | None
    arguments: dict[str, Any] | None
    raw_protocol: str
    raw_response: str
    trailing_text: str
    confidence: Confidence
    rejection_reason: str | None = None

    @property
    def executable(self) -> bool:
        return self.confidence == "exact" and self.name is not None and self.arguments is not None


def _schema_valid(value: object, schema: dict[str, Any]) -> bool:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            return False
        required = set(schema.get("required", []))
        if not required.issubset(value):
            return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and not set(value).issubset(properties):
            return False
        return all(
            key not in properties or _schema_valid(item, properties[key])
            for key, item in value.items()
        )
    if schema_type == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif schema_type == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif schema_type == "string":
        valid = isinstance(value, str)
    elif schema_type == "boolean":
        valid = isinstance(value, bool)
    elif schema_type == "array":
        valid = isinstance(value, list) and all(
            _schema_valid(item, schema.get("items", {})) for item in value
        )
    else:
        valid = True
    return valid and ("enum" not in schema or value in schema["enum"])


def normalize_tool_call(
    raw: str,
    *,
    tools: dict[str, dict[str, Any]],
    manifest: GGUFAdapterManifest,
) -> NormalizedToolCall:
    spec = manifest.tool_call
    if (
        spec.encoding,
        spec.name_source,
        spec.arguments_source,
    ) != ("name_json_then_text", "first_nonempty_line", "first_json_object_after_name"):
        raise ValueError("Unsupported declarative tool-call extraction contract")
    cleaned = re.sub(r"^\s*<\|assistant\|>\s*", "", raw)
    lines = cleaned.splitlines()
    first_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_index is None:
        return NormalizedToolCall(None, None, "name_json_then_text", raw, "", "rejected", "empty")
    if (
        first_index > 0
        and spec.leading_text_policy == "reject"
        and any(line.strip() for line in lines[:first_index])
    ):
        return NormalizedToolCall(
            None, None, "name_json_then_text", raw, "", "rejected", "leading_text"
        )
    name = lines[first_index].strip()
    if name not in tools:
        return NormalizedToolCall(
            name, None, "name_json_then_text", raw, "", "rejected", "unknown_tool"
        )
    remainder = "\n".join(lines[first_index + 1 :]).lstrip()
    try:
        arguments, end = json.JSONDecoder().raw_decode(remainder)
    except json.JSONDecodeError:
        return NormalizedToolCall(
            name, None, "name_json_then_text", raw, "", "rejected", "invalid_json"
        )
    trailing = remainder[end:].strip()
    if spec.multiple_json_policy == "reject" and trailing.startswith("{"):
        try:
            second, _ = json.JSONDecoder().raw_decode(trailing)
        except json.JSONDecodeError:
            second = None
        if isinstance(second, dict):
            return NormalizedToolCall(
                name, None, "name_json_then_text", raw, trailing, "rejected", "multiple_json"
            )
    if not isinstance(arguments, dict) or not _schema_valid(arguments, tools[name]):
        return NormalizedToolCall(
            name, None, "name_json_then_text", raw, trailing, "rejected", "schema_validation"
        )
    return NormalizedToolCall(name, arguments, "name_json_then_text", raw, trailing, "exact")


def build_reinjection(
    call: NormalizedToolCall, tool_result: object, manifest: GGUFAdapterManifest
) -> tuple[dict[str, str], dict[str, str]]:
    if not call.executable:
        raise ValueError("Only exact normalized calls can be reinjected")
    spec = manifest.reinjection
    call_spec = spec.call_message
    result_spec = spec.result_message
    assistant = {
        "role": call_spec["role"],
        call_spec["name_field"]: str(call.name),
        call_spec["arguments_field"]: json.dumps(call.arguments, separators=(",", ":")),
    }
    result = {
        "role": result_spec["role"],
        "metadata": result_spec["metadata"],
        "content": str(tool_result),
    }
    return assistant, result
