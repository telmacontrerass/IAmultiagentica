"""Structured Ollama identity, idempotency, conflict and safe rollback."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from ci2lab.runtime.ollama import normalize_ollama_model_name

IdentityState = Literal[
    "CREATE_REQUIRED",
    "ALREADY_IMPORTED_EQUIVALENT",
    "IMPORT_CONFLICT",
    "PROFILE_MODEL_INCONSISTENT",
    "EXTERNAL_MODEL_UNTRACKED",
]


@dataclass(frozen=True)
class OllamaModelSnapshot:
    requested_tag: str
    canonical_tag: str
    exists: bool
    digest: str | None = None
    modelfile: str | None = None
    template: str | None = None
    parameters: str | dict[str, Any] | None = None
    family: str | None = None
    architecture: str | None = None
    quantization: str | None = None
    context_length: int | None = None
    capabilities: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class ExpectedOllamaIdentity:
    tag: str
    gguf_sha256: str
    repo: str
    filename: str
    architecture: str
    quantization: str
    template_sha256: str | None
    ollama_template_sha256: str | None
    modelfile_sha256: str
    context_length: int
    parameters: dict[str, Any]
    stops: tuple[str, ...]
    protocol: str
    adapter: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "gguf_sha256": self.gguf_sha256,
            "repo": self.repo,
            "filename": self.filename,
            "architecture": self.architecture,
            "quantization": self.quantization,
            "template_sha256": self.template_sha256,
            "ollama_template_sha256": self.ollama_template_sha256,
            "modelfile_sha256": self.modelfile_sha256,
            "context_length": self.context_length,
            "parameters": self.parameters,
            "stops": list(self.stops),
            "protocol": self.protocol,
            "adapter": self.adapter,
        }


@dataclass(frozen=True)
class IdentityDecision:
    state: IdentityState
    differences: tuple[str, ...] = ()


def snapshot_ollama_model(tag: str) -> OllamaModelSnapshot:
    """Capture `ollama show --json`; missing tags are normal snapshots."""
    completed = subprocess.run(
        ["ollama", "show", tag, "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        return OllamaModelSnapshot(
            tag,
            normalize_ollama_model_name(tag),
            False,
            error=(completed.stderr or completed.stdout).strip() or "model not found",
        )
    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return OllamaModelSnapshot(
            tag, normalize_ollama_model_name(tag), False, error=f"invalid show JSON: {exc}"
        )
    if not isinstance(raw, dict):
        return OllamaModelSnapshot(
            tag, normalize_ollama_model_name(tag), False, error="invalid show JSON object"
        )
    details = cast(
        dict[str, Any], raw.get("details") if isinstance(raw.get("details"), dict) else {}
    )
    model_info = cast(
        dict[str, Any],
        raw.get("model_info") if isinstance(raw.get("model_info"), dict) else {},
    )
    context = next(
        (
            int(value)
            for key, value in model_info.items()
            if key.endswith(".context_length") and isinstance(value, (int, float))
        ),
        None,
    )
    return OllamaModelSnapshot(
        requested_tag=tag,
        canonical_tag=normalize_ollama_model_name(str(raw.get("name") or tag)),
        exists=True,
        digest=str(raw.get("digest")) if raw.get("digest") else None,
        modelfile=str(raw.get("modelfile")) if raw.get("modelfile") is not None else None,
        template=str(raw.get("template")) if raw.get("template") is not None else None,
        parameters=raw.get("parameters"),
        family=str(details.get("family")) if details.get("family") else None,
        architecture=str(details.get("families", [None])[0]) if details.get("families") else None,
        quantization=str(details.get("quantization_level"))
        if details.get("quantization_level")
        else None,
        context_length=context,
        capabilities=tuple(str(item) for item in raw.get("capabilities", [])),
        details=dict(details),
        raw=raw,
    )


def expected_identity(profile: Any, modelfile: str) -> ExpectedOllamaIdentity:
    source = profile.source
    tools = profile.capabilities.tool_calling
    template_parts = modelfile.split('TEMPLATE """', 1)
    rendered_template = (
        template_parts[1].split('"""', 1)[0].lstrip("\r\n") if len(template_parts) == 2 else ""
    )
    return ExpectedOllamaIdentity(
        tag=normalize_ollama_model_name(profile.ollama_tag),
        gguf_sha256=str(source.get("sha256") or ""),
        repo=str(source.get("repo") or ""),
        filename=str(source.get("filename") or ""),
        architecture=str(source.get("architecture") or "unknown"),
        quantization=str(source.get("quantization") or "unknown"),
        template_sha256=str(source["template_sha256"]) if source.get("template_sha256") else None,
        ollama_template_sha256=(
            hashlib.sha256(rendered_template.encode()).hexdigest() if rendered_template else None
        ),
        modelfile_sha256=hashlib.sha256(modelfile.encode()).hexdigest(),
        context_length=profile.context_length,
        parameters=dict(profile.parameters),
        stops=tuple(profile.stops),
        protocol=tools.protocol,
        adapter=tools.adapter,
    )


def decide_identity(
    expected: ExpectedOllamaIdentity,
    snapshot: OllamaModelSnapshot,
    registered_identity: dict[str, Any] | None,
) -> IdentityDecision:
    """Classify absent/equivalent/conflicting and tracked/untracked states."""
    if not snapshot.exists:
        return IdentityDecision(
            "PROFILE_MODEL_INCONSISTENT" if registered_identity else "CREATE_REQUIRED"
        )
    if registered_identity is None:
        return IdentityDecision("EXTERNAL_MODEL_UNTRACKED")
    differences: list[str] = []
    current = expected.to_dict()
    for key in (
        "gguf_sha256",
        "template_sha256",
        "ollama_template_sha256",
        "modelfile_sha256",
        "architecture",
        "quantization",
        "context_length",
        "parameters",
        "stops",
        "protocol",
        "adapter",
    ):
        existing = registered_identity.get(key)
        wanted = current[key]
        if existing != wanted:
            differences.append(f"{key}: registered={existing!r}, expected={wanted!r}")
    if normalize_ollama_model_name(snapshot.canonical_tag) != expected.tag:
        differences.append(f"tag: ollama={snapshot.canonical_tag!r}, expected={expected.tag!r}")
    return IdentityDecision(
        "IMPORT_CONFLICT" if differences else "ALREADY_IMPORTED_EQUIVALENT",
        tuple(differences),
    )


def verify_post_create(
    expected: ExpectedOllamaIdentity, snapshot: OllamaModelSnapshot
) -> tuple[str, ...]:
    """Compare everything Ollama exposes; CI2Lab-only hash is checked in registry."""
    differences: list[str] = []
    if not snapshot.exists:
        return ("model absent after ollama create",)
    if normalize_ollama_model_name(snapshot.canonical_tag) != expected.tag:
        differences.append("canonical tag mismatch")
    if snapshot.architecture and expected.architecture not in {"unknown", snapshot.architecture}:
        differences.append("architecture mismatch")
    if snapshot.quantization and expected.quantization not in {"unknown", snapshot.quantization}:
        differences.append("quantization mismatch")
    if snapshot.context_length and snapshot.context_length != expected.context_length:
        differences.append("context length mismatch")
    if snapshot.template and expected.ollama_template_sha256:
        actual_template_hash = hashlib.sha256(snapshot.template.encode()).hexdigest()
        if actual_template_hash != expected.ollama_template_sha256:
            differences.append("template mismatch")
    if (
        snapshot.modelfile
        and f"PARAMETER num_ctx {expected.context_length}" not in snapshot.modelfile
    ):
        differences.append("modelfile context parameter mismatch")
    if snapshot.modelfile:
        for name, value in expected.parameters.items():
            if f"PARAMETER {name} {value}" not in snapshot.modelfile:
                differences.append(f"modelfile parameter mismatch: {name}")
        for stop in expected.stops:
            rendered = json.dumps(stop, ensure_ascii=False)
            if f"PARAMETER stop {rendered}" not in snapshot.modelfile:
                differences.append(f"modelfile stop mismatch: {stop}")
    return tuple(differences)


def safe_rollback_created_model(
    tag: str,
    *,
    before: OllamaModelSnapshot,
    after_creation: OllamaModelSnapshot,
) -> bool:
    """Delete only an attributed, unchanged model created by this attempt."""
    if before.exists or not after_creation.exists or not after_creation.digest:
        return False
    current = snapshot_ollama_model(tag)
    if not current.exists or current.digest != after_creation.digest:
        return False
    completed = subprocess.run(
        ["ollama", "rm", tag],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode == 0
