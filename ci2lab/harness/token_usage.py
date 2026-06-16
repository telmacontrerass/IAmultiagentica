"""Token usage accounting shared by CLI, UI, sessions and run logs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenUsage:
    """Provider-reported token usage for one or more model calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    source: str = "provider"
    estimated: bool = False

    @classmethod
    def from_provider(cls, data: dict[str, Any] | None, *, model: str) -> "TokenUsage | None":
        if not isinstance(data, dict):
            return None
        prompt_tokens = _safe_int(
            data.get("prompt_tokens", data.get("prompt_eval_count"))
        )
        completion_tokens = _safe_int(
            data.get("completion_tokens", data.get("eval_count"))
        )
        total_tokens = _safe_int(data.get("total_tokens"))
        if total_tokens <= 0 and (prompt_tokens or completion_tokens):
            total_tokens = prompt_tokens + completion_tokens
        if prompt_tokens <= 0 and completion_tokens <= 0 and total_tokens <= 0:
            return None
        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model=model,
            source="provider",
            estimated=False,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TokenUsage":
        if not isinstance(data, dict):
            return cls()
        return cls(
            prompt_tokens=_safe_int(data.get("prompt_tokens")),
            completion_tokens=_safe_int(data.get("completion_tokens")),
            total_tokens=_safe_int(data.get("total_tokens")),
            model=str(data.get("model") or ""),
            source=str(data.get("source") or "provider"),
            estimated=bool(data.get("estimated")),
        )

    @property
    def available(self) -> bool:
        return self.total_tokens > 0 or self.prompt_tokens > 0 or self.completion_tokens > 0

    def add(self, other: "TokenUsage | None") -> None:
        if other is None or not other.available:
            return
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens or (
            other.prompt_tokens + other.completion_tokens
        )
        self.model = other.model or self.model
        self.source = other.source or self.source
        self.estimated = self.estimated or other.estimated

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "source": self.source,
            "estimated": self.estimated,
            "available": self.available,
        }


@dataclass
class TokenUsageState:
    """Mutable token accounting for one agent config/session."""

    last_call: TokenUsage | None = None
    turn: TokenUsage = field(default_factory=TokenUsage)
    session: TokenUsage = field(default_factory=TokenUsage)
    calls: list[TokenUsage] = field(default_factory=list)

    def reset_turn(self) -> None:
        self.last_call = None
        self.turn = TokenUsage()
        self.calls = []

    def hydrate_session(self, data: dict[str, Any] | None) -> None:
        if not isinstance(data, dict):
            return
        session_total = data.get("session_total") or data.get("total") or data
        loaded = TokenUsage.from_dict(session_total)
        if loaded.available and not self.session.available:
            self.session = loaded

    def record_call(self, usage: TokenUsage | None) -> None:
        if usage is None or not usage.available:
            return
        self.last_call = usage
        self.turn.add(usage)
        self.session.add(usage)
        self.calls.append(usage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_call": self.last_call.to_dict() if self.last_call else None,
            "last_turn": self.turn.to_dict(),
            "session_total": self.session.to_dict(),
            "calls": [usage.to_dict() for usage in self.calls],
        }


def format_token_usage_line(state: TokenUsageState) -> str:
    turn = state.turn
    session = state.session
    if not turn.available:
        return "Tokens: no disponibles desde el proveedor"
    model = turn.model or session.model or "?"
    return (
        "Tokens: "
        f"entrada {turn.prompt_tokens:,} | "
        f"salida {turn.completion_tokens:,} | "
        f"turno {turn.total_tokens:,} | "
        f"conversacion {session.total_tokens:,} | "
        f"modelo {model}"
    )


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
