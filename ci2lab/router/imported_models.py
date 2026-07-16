"""Local registry for user-imported GGUF models.

The bundled ``models.json`` remains the curated global catalog. This module is
for machine-local model profiles created from concrete GGUF files, usually from
Hugging Face, where the Ollama tag, template, context window and CI2Lab tool mode
must travel together without bloating the model name.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ci2lab.contracts import ToolMode
from ci2lab.router.gguf_import.capabilities import ImportedCapabilities
from ci2lab.runtime.ollama import ollama_model_names_equivalent

TEMPLATES_PATH = Path(__file__).resolve().parents[1] / "catalog" / "model_templates.json"
REGISTRY_ENV = "CI2LAB_IMPORTED_MODELS_PATH"
_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_OLLAMA_MODEL_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*"
    r"(?::[A-Za-z0-9][A-Za-z0-9_.-]*)?$"
)


@dataclass(frozen=True)
class ModelTemplate:
    """Ollama prompt template metadata for an imported model family."""

    id: str
    family: str
    template: str
    stops: tuple[str, ...] = ()
    default_parameters: dict[str, float | int | str | bool] = field(default_factory=dict)
    default_tool_mode: ToolMode = "fenced"
    description: str = ""


@dataclass(frozen=True)
class ImportedModelProfile:
    """Machine-local execution profile for a concrete imported model."""

    id: str
    backend: str
    ollama_tag: str
    source: dict[str, Any]
    family: str
    template_id: str
    context_length: int
    tool_mode: ToolMode
    parameters: dict[str, float | int | str | bool] = field(default_factory=dict)
    stops: tuple[str, ...] = ()
    supports_tools: bool = False
    tool_capabilities: dict[str, str] = field(default_factory=dict)
    verification: dict[str, bool] = field(default_factory=dict)
    capabilities: ImportedCapabilities = field(default_factory=ImportedCapabilities)

    @property
    def display_name(self) -> str:
        return self.id

    @property
    def local_path(self) -> str:
        return str(self.source.get("local_path") or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "backend": self.backend,
            "ollama_tag": self.ollama_tag,
            "source": dict(self.source),
            "family": self.family,
            "template_id": self.template_id,
            "context_length": self.context_length,
            "tool_mode": self.tool_mode,
            "parameters": dict(self.parameters),
            "stops": list(self.stops),
            "supports_tools": self.supports_tools,
            "tool_capabilities": dict(self.tool_capabilities),
            "verification": dict(self.verification),
            "capabilities": self.capabilities.to_dict(),
        }


def default_imported_models_path() -> Path:
    """Return the registry path, allowing tests/operators to override it."""
    if raw := os.environ.get(REGISTRY_ENV):
        return Path(raw).expanduser()
    return Path.home() / ".ci2lab" / "models" / "imported_models.json"


def _coerce_tool_mode(value: object) -> ToolMode:
    return "native" if str(value).strip().lower() == "native" else "fenced"


def load_model_templates(path: Path = TEMPLATES_PATH) -> dict[str, ModelTemplate]:
    """Load bundled prompt templates by id."""
    data = json.loads(path.read_text(encoding="utf-8"))
    templates: dict[str, ModelTemplate] = {}
    for item in data.get("templates", []):
        template_id = str(item.get("id") or "").strip()
        if not template_id:
            continue
        templates[template_id] = ModelTemplate(
            id=template_id,
            family=str(item.get("family") or ""),
            template=str(item.get("template") or ""),
            stops=tuple(str(stop) for stop in item.get("stops", []) if str(stop)),
            default_parameters=dict(item.get("default_parameters") or {}),
            default_tool_mode=_coerce_tool_mode(item.get("default_tool_mode", "fenced")),
            description=str(item.get("description") or ""),
        )
    return templates


def get_model_template(template_id: str) -> ModelTemplate:
    """Return one template or raise ``ValueError`` with a user-facing message."""
    templates = load_model_templates()
    try:
        return templates[template_id]
    except KeyError as exc:
        available = ", ".join(sorted(templates)) or "(none)"
        raise ValueError(f"Unknown model template '{template_id}'. Available: {available}") from exc


def _profile_from_dict(item: dict[str, Any]) -> ImportedModelProfile | None:
    model_id = str(item.get("id") or "").strip()
    if not model_id:
        return None
    try:
        context_length = int(item.get("context_length") or 8192)
    except (TypeError, ValueError):
        context_length = 8192
    return ImportedModelProfile(
        id=model_id,
        backend=str(item.get("backend") or "ollama"),
        ollama_tag=str(item.get("ollama_tag") or model_id),
        source=dict(item.get("source") or {}),
        family=str(item.get("family") or ""),
        template_id=str(item.get("template_id") or item.get("template") or ""),
        context_length=context_length,
        tool_mode=_coerce_tool_mode(item.get("tool_mode", "fenced")),
        parameters=dict(item.get("parameters") or {}),
        stops=tuple(str(stop) for stop in item.get("stops", []) if str(stop)),
        # Legacy supports_tools=true meant "preferred/attemptable", not verified.
        supports_tools=bool(item.get("supports_tools", False)),
        tool_capabilities={
            str(key): str(value) for key, value in dict(item.get("tool_capabilities") or {}).items()
        },
        verification={
            str(key): bool(value) for key, value in dict(item.get("verification") or {}).items()
        },
        capabilities=ImportedCapabilities.from_dict(item.get("capabilities")),
    )


def load_imported_model_registry(path: Path | None = None) -> list[ImportedModelProfile]:
    """Load imported model profiles from the local registry."""
    registry_path = path or default_imported_models_path()
    if not registry_path.is_file():
        return []
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_models = data.get("models", []) if isinstance(data, dict) else []
    profiles: list[ImportedModelProfile] = []
    for item in raw_models:
        if isinstance(item, dict):
            profile = _profile_from_dict(item)
            if profile is not None:
                profiles.append(profile)
    return profiles


def find_imported_model_by_tag(tag: str) -> ImportedModelProfile | None:
    """Match an imported model by id or Ollama tag."""
    for profile in load_imported_model_registry():
        if ollama_model_names_equivalent(tag, profile.id) or ollama_model_names_equivalent(
            tag, profile.ollama_tag
        ):
            return profile
    return None


def save_imported_model_profile(
    profile: ImportedModelProfile,
    *,
    path: Path | None = None,
) -> Path:
    """Upsert one imported profile into the local registry."""
    registry_path = path or default_imported_models_path()
    models = [item for item in load_imported_model_registry(registry_path) if item.id != profile.id]
    models.append(profile)
    _write_registry_atomic(registry_path, models)
    return registry_path


def replace_imported_model_registry(
    profiles: list[ImportedModelProfile], *, path: Path | None = None
) -> Path:
    """Replace the local registry after an explicit model consolidation."""
    registry_path = path or default_imported_models_path()
    _write_registry_atomic(registry_path, profiles)
    return registry_path


def _write_registry_atomic(path: Path, profiles: list[ImportedModelProfile]) -> None:
    """Replace a registry atomically so interruption cannot leave partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"models": [item.to_dict() for item in sorted(profiles, key=lambda m: m.id)]}
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_imported_profile(
    *,
    model_id: str,
    repo: str,
    filename: str,
    local_path: str,
    family: str,
    template_id: str,
    context_length: int,
    ollama_tag: str | None = None,
    tool_mode: str | None = None,
    parameters: dict[str, float | int | str | bool] | None = None,
) -> ImportedModelProfile:
    """Construct a profile from CLI import arguments and template defaults."""
    normalized_id = model_id.strip()
    if not _PROFILE_ID_RE.fullmatch(normalized_id):
        raise ValueError("Invalid CI2Lab profile id. Use a short alias such as 'glm4'.")
    normalized_tag = (ollama_tag or normalized_id).strip()
    if not _OLLAMA_MODEL_ID_RE.fullmatch(normalized_tag):
        raise ValueError("Invalid Ollama tag. Use a name such as 'ci2lab/glm4:q4_k_m'.")
    if context_length <= 0:
        raise ValueError("Context length must be a positive integer.")
    template = get_model_template(template_id)
    merged_parameters = dict(template.default_parameters)
    if parameters:
        merged_parameters.update(parameters)
    return ImportedModelProfile(
        id=normalized_id,
        backend="ollama",
        ollama_tag=normalized_tag,
        source={
            "type": "huggingface",
            "repo": repo,
            "filename": filename,
            "local_path": local_path,
        },
        family=family,
        template_id=template_id,
        context_length=context_length,
        tool_mode=_coerce_tool_mode(tool_mode or template.default_tool_mode),
        parameters=merged_parameters,
        stops=template.stops,
        supports_tools=False,
        tool_capabilities={"native": "unknown", "fenced": "unknown", "json": "unknown"},
        verification={
            "created": False,
            "verified": False,
            "chat_verified": False,
            "native_tools_verified": False,
            "fenced_tools_verified": False,
        },
        capabilities=ImportedCapabilities(),
    )


def _quote_modelfile_value(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_ollama_modelfile(profile: ImportedModelProfile) -> str:
    """Render an Ollama Modelfile for an imported GGUF profile."""
    template = get_model_template(profile.template_id)
    lines = [
        f"FROM {profile.local_path}",
        'TEMPLATE """',
        template.template,
        '"""',
        f"PARAMETER num_ctx {int(profile.context_length)}",
    ]
    for key, value in profile.parameters.items():
        lines.append(f"PARAMETER {key} {value}")
    for stop in profile.stops:
        lines.append(f"PARAMETER stop {_quote_modelfile_value(stop)}")
    return "\n".join(lines) + "\n"


def create_ollama_model(
    profile: ImportedModelProfile,
    *,
    dry_run: bool = False,
) -> tuple[str, subprocess.CompletedProcess[str] | None]:
    """Create the Ollama model or return the dry-run Modelfile."""
    modelfile = render_ollama_modelfile(profile)
    if dry_run:
        return modelfile, None

    with tempfile.TemporaryDirectory(prefix="ci2lab-model-") as tmp:
        modelfile_path = Path(tmp) / "Modelfile"
        modelfile_path.write_text(modelfile, encoding="utf-8")
        completed = subprocess.run(
            ["ollama", "create", profile.ollama_tag, "-f", str(modelfile_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    return modelfile, completed


def verify_ollama_model(profile: ImportedModelProfile) -> subprocess.CompletedProcess[str]:
    """Confirm non-destructively that Ollama can inspect a newly-created model."""
    return subprocess.run(
        ["ollama", "show", profile.ollama_tag, "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def verify_ollama_inference(profile: ImportedModelProfile) -> subprocess.CompletedProcess[str]:
    """Require a deterministic minimal inference before registry promotion."""
    return subprocess.run(
        ["ollama", "run", profile.ollama_tag, "Respond only with OK."],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
