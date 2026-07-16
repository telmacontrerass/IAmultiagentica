"""Declarative execution candidates and future template-adaptation contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ImportCandidate:
    runtime: str
    template_origin: str
    template_path: Path | None
    tool_mode: str
    parser: str | None = None
    observation_role: str | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["template_path"] = str(self.template_path) if self.template_path else None
        return data


@dataclass(frozen=True)
class RuntimeTemplateContract:
    messages_variable: str = "messages"
    tools_variable: str = "tools"
    tool_choice_variable: str = "tool_choice"


@dataclass(frozen=True)
class AdaptedTemplateCandidate:
    template: str
    adapter: str
    notes: tuple[str, ...] = ()


class TemplateAdapter(Protocol):
    def detect(self, inspection: object) -> bool: ...

    def create_candidate(
        self, original_template: str, runtime_contract: RuntimeTemplateContract
    ) -> AdaptedTemplateCandidate: ...


BUILTIN_CANDIDATES = {
    "ollama_go_fenced": ImportCandidate(
        "ollama", "ci2lab_go", None, "fenced", "ci2lab_fallback", "observation"
    ),
    "ollama_go_native": ImportCandidate("ollama", "ci2lab_go", None, "native"),
    "llama_cpp_original_jinja": ImportCandidate("llama.cpp", "gguf_original", None, "native"),
    "llama_cpp_adapted_jinja": ImportCandidate("llama.cpp", "adapted", None, "native"),
}
