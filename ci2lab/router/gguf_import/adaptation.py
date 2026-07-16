"""Explicit experimental adaptation of legacy GLM tools to llama.cpp globals."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

ADAPTER_ID = "experimental_glm_global_tools_v1"


@dataclass(frozen=True)
class AdaptationManifest:
    origin: str
    original_template_sha256: str
    adapted_template_sha256: str
    adapter_id: str
    runtime: str
    runtime_version: str
    changes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_text_exact(path: Path, text: str) -> None:
    """Write UTF-8 without platform newline translation so manifest hashes are exact."""
    path.write_bytes(text.encode("utf-8"))


def adapt_glm_global_tools(original: str) -> tuple[str, AdaptationManifest, str]:
    """Compatibility wrapper over the declarative transformation engine."""
    from dataclasses import replace

    from ci2lab.router.gguf_import.adapter_manifest import get_adapter
    from ci2lab.router.gguf_import.transforms import apply_template_transform

    declaration = get_adapter(ADAPTER_ID)
    declaration = replace(
        declaration,
        match=replace(declaration.match, original_template_sha256=sha256_text(original)),
        transform=replace(
            declaration.transform,
            expected_adapted_template_sha256="pending",
        ),
    )
    # Derive the expected hash once, then run the same engine with its postcondition enabled.
    spec = declaration.transform
    anchor = spec.anchor
    message = spec.message
    bridge = (
        "{% if tools is defined and tools %}"
        f"{{% set messages = [{{'role': {message['role']!r}, 'metadata': {message['metadata']!r}, "
        f"'content': {message['content']!r}, 'tools': tools}}] + messages %}}{{% endif %}}"
    )
    preview = original.replace(anchor, anchor + bridge, 1)
    declaration = replace(
        declaration,
        transform=replace(spec, expected_adapted_template_sha256=sha256_text(preview)),
    )
    result = apply_template_transform(original, declaration)
    manifest = AdaptationManifest(
        origin="gguf_adapted",
        original_template_sha256=sha256_text(original),
        adapted_template_sha256=result.adapted_sha256,
        adapter_id=ADAPTER_ID,
        runtime="llama.cpp",
        runtime_version="b9994",
        changes=(
            "Prepend a synthetic empty system message carrying global tools when tools are present",
        ),
    )
    return result.adapted, manifest, result.diff
