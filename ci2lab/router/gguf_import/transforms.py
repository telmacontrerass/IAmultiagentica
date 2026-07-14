"""Allow-listed, reproducible transformations for experimental GGUF templates."""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass

from ci2lab.router.gguf_import.adapter_manifest import GGUFAdapterManifest


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TemplateTransformResult:
    original: str
    adapted: str
    original_sha256: str
    adapted_sha256: str
    diff: str
    transform_type: str


def apply_template_transform(
    original: str, manifest: GGUFAdapterManifest
) -> TemplateTransformResult:
    expected = manifest.match.original_template_sha256
    actual = _sha256_text(original)
    if actual != expected:
        raise ValueError(f"Template hash mismatch: expected {expected}, got {actual}")
    spec = manifest.transform
    if spec.type != "inject_global_tools_as_message":
        raise ValueError(f"Unsupported safe template transform: {spec.type}")
    if spec.position != "prepend" or spec.message.get("tools_from") != "global.tools":
        raise ValueError("Unsupported global-tools message mapping")
    if original.count(spec.anchor) != 1:
        raise ValueError("Transform anchor must appear exactly once")
    if original.count("item['tools']") < 1:
        raise ValueError("Target template does not consume message tools")
    message = spec.message
    bridge = (
        "{% if tools is defined and tools %}"
        "{% set messages = [{'role': "
        + repr(message["role"])
        + ", 'metadata': "
        + repr(message["metadata"])
        + ", 'content': "
        + repr(message["content"])
        + ", 'tools': tools}] + messages %}{% endif %}"
    )
    adapted = original.replace(spec.anchor, spec.anchor + bridge, 1)
    if adapted.count(bridge) != 1 or not adapted.startswith(spec.anchor):
        raise ValueError("Template transformation postcondition failed")
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            adapted.splitlines(keepends=True),
            fromfile="original_template.jinja",
            tofile="adapted_template.jinja",
        )
    )
    adapted_hash = _sha256_text(adapted)
    if adapted_hash != spec.expected_adapted_template_sha256:
        raise ValueError("Adapted template hash postcondition failed")
    return TemplateTransformResult(
        original,
        adapted,
        actual,
        adapted_hash,
        diff,
        spec.type,
    )
