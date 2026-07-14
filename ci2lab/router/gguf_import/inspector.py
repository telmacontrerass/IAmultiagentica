"""Small dependency-free GGUF metadata reader and declarative Jinja analysis."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

_SIZES = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


def _read(stream: BinaryIO, fmt: str) -> tuple[Any, ...]:
    size = struct.calcsize("<" + fmt)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("Truncated GGUF metadata")
    return struct.unpack("<" + fmt, data)


def _string(stream: BinaryIO) -> str:
    length = int(_read(stream, "Q")[0])
    return stream.read(length).decode("utf-8", errors="replace")


def _value(stream: BinaryIO, kind: int) -> object:
    if kind == 8:
        return _string(stream)
    if kind == 9:
        subtype, length = (int(v) for v in _read(stream, "IQ"))
        return [_value(stream, subtype) for _ in range(length)]
    fmt = _SIZES.get(kind)
    if fmt is None:
        raise ValueError(f"Unsupported GGUF metadata type: {kind}")
    return _read(stream, fmt)[0]


def read_gguf_metadata(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise ValueError(f"Not a GGUF file: {path}")
        version = int(_read(stream, "I")[0])
        if version not in {2, 3}:
            raise ValueError(f"Unsupported GGUF version: {version}")
        _tensor_count, metadata_count = (int(v) for v in _read(stream, "QQ"))
        return {
            _string(stream): _value(stream, int(_read(stream, "I")[0]))
            for _ in range(metadata_count)
        }


@dataclass(frozen=True)
class TemplateAnalysis:
    template_present: bool
    template_sha256: str | None
    template_size_bytes: int
    tool_schema_sources: tuple[str, ...] = ()
    tool_call_name_sources: tuple[str, ...] = ()
    tool_call_argument_sources: tuple[str, ...] = ()
    tool_result_roles: tuple[str, ...] = ()
    patterns: dict[str, bool] = field(default_factory=dict)


def analyze_template(template: str | None) -> TemplateAnalysis:
    text = template or ""
    patterns = {
        "global_tools": "tools is defined" in text or "tools |" in text,
        "messages_tools": "message.tools" in text
        or "item['tools']" in text
        or 'item["tools"]' in text
        or ("messages[" in text and ".tools" in text),
        "tool_calls": "tool_calls" in text,
        "assistant_metadata": "metadata" in text,
        "role_tool": "'tool'" in text or '"tool"' in text,
        "role_observation": "observation" in text,
        "arguments_in_content": "content" in text,
        "xml_blocks": "<tool" in text or "</" in text,
        "json_blocks": "tojson" in text or "json" in text.lower(),
        "python_branch": "python" in text,
        "simple_browser_branch": "simple_browser" in text,
        "cogview_branch": "cogview" in text,
    }
    encoded = text.encode("utf-8")
    return TemplateAnalysis(
        bool(text),
        hashlib.sha256(encoded).hexdigest() if text else None,
        len(encoded),
        ("messages[*].tools",)
        if patterns["messages_tools"]
        else (("tools",) if patterns["global_tools"] else ()),
        ("assistant.metadata",)
        if patterns["assistant_metadata"]
        else (("assistant.tool_calls",) if patterns["tool_calls"] else ()),
        ("assistant.content",) if patterns["arguments_in_content"] else (),
        ("observation",)
        if patterns["role_observation"]
        else (("tool",) if patterns["role_tool"] else ()),
        patterns,
    )


@dataclass(frozen=True)
class GGUFInspection:
    architecture: str | None
    name: str | None
    context_length: int | None
    chat_template: str | None
    special_tokens: dict[str, object]
    template_analysis: TemplateAnalysis
    metadata: dict[str, object]
    quantization: str = "unknown"
    tokenizer: str = "unknown"
    pretokenizer: str = "unknown"
    tool_call_format: str = "unknown"
    tool_result_role: str = "unknown"
    inspection_tool: str = "ci2lab_structured_gguf_reader"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        return data


def inspect_gguf(path: str | Path) -> GGUFInspection:
    metadata = read_gguf_metadata(Path(path))
    architecture = str(metadata.get("general.architecture") or "") or None
    context_key = f"{architecture}.context_length" if architecture else ""
    raw_context = metadata.get(context_key)
    template = metadata.get("tokenizer.chat_template")
    specials = {
        key: value
        for key, value in metadata.items()
        if key.startswith("tokenizer.ggml.")
        and (key.endswith("_token_id") or "bos_token" in key or "eos_token" in key)
    }
    report_metadata = {
        key: value
        for key, value in metadata.items()
        if not isinstance(value, list) or len(value) <= 32
    }
    analysis = analyze_template(str(template) if template is not None else None)
    file_types = {2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 15: "Q4_K_M"}
    raw_file_type = metadata.get("general.file_type")
    quantization = (
        file_types.get(raw_file_type, "unknown") if isinstance(raw_file_type, int) else "unknown"
    )
    call_format = (
        "openai_tool_calls_xml"
        if analysis.patterns.get("tool_calls") and analysis.patterns.get("xml_blocks")
        else ("family_text_protocol" if analysis.patterns.get("assistant_metadata") else "unknown")
    )
    return GGUFInspection(
        architecture,
        str(metadata.get("general.name") or "") or None,
        int(raw_context) if isinstance(raw_context, (int, float, str)) else None,
        str(template) if template is not None else None,
        specials,
        analysis,
        report_metadata,
        quantization,
        str(metadata.get("tokenizer.ggml.model") or "unknown"),
        str(metadata.get("tokenizer.ggml.pre") or "unknown"),
        call_format,
        analysis.tool_result_roles[0] if analysis.tool_result_roles else "unknown",
    )
