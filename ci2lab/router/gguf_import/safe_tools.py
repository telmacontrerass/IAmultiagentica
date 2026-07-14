"""Allow-listed tools and round guards used only by experimental validation suites."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ci2lab.router.gguf_import.normalizer import NormalizedToolCall


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    value: object | None = None
    error: str | None = None


def execute_validation_tool(
    name: str, arguments: dict[str, Any], *, fixture_root: Path | None = None
) -> ToolOutcome:
    """Execute only deterministic built-ins; never model-generated code."""
    if name == "add":
        return ToolOutcome(True, int(arguments["a"]) + int(arguments["b"]))
    if name == "echo":
        return ToolOutcome(True, str(arguments["text"]))
    if name == "annotate":
        return ToolOutcome(True, {"text": str(arguments["text"]), "note": arguments.get("note")})
    if name == "configure":
        return ToolOutcome(True, dict(arguments))
    if name == "set_mode":
        return ToolOutcome(True, str(arguments["mode"]))
    if name == "opaque_value":
        return ToolOutcome(True, f"OBS_{secrets.token_hex(12).upper()}")
    if name == "read_fixture":
        if fixture_root is None:
            return ToolOutcome(False, error="fixture_root_unavailable")
        requested = Path(str(arguments["path"]))
        if requested.is_absolute():
            return ToolOutcome(False, error="fixture_path_rejected")
        root = fixture_root.resolve()
        target = (root / requested).resolve()
        if root not in target.parents or not target.is_file():
            return ToolOutcome(False, error="fixture_path_rejected")
        return ToolOutcome(True, target.read_text(encoding="utf-8"))
    if name in {"fail_safely", "always_fail"}:
        return ToolOutcome(False, error="intentional_validation_error")
    return ToolOutcome(False, error="tool_not_allowlisted")


@dataclass
class AdaptedRoundGuard:
    max_rounds: int
    rounds: int = 0
    signatures: set[str] = field(default_factory=set)

    def accept(self, call: NormalizedToolCall) -> tuple[bool, str | None]:
        if not call.executable:
            return False, "not_exact"
        signature = json.dumps([call.name, call.arguments], sort_keys=True, separators=(",", ":"))
        if signature in self.signatures:
            return False, "repeated_call"
        if self.rounds >= self.max_rounds:
            return False, "round_limit"
        self.signatures.add(signature)
        self.rounds += 1
        return True, None
