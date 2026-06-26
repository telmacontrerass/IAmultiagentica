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
    def from_provider(cls, data: dict[str, Any] | None, *, model: str) -> TokenUsage | None:
        """Build usage from a provider usage payload.

        Accepts both OpenAI-style (``prompt_tokens``/``completion_tokens``/
        ``total_tokens``) and Ollama-style (``prompt_eval_count``/``eval_count``)
        keys. The total is derived from prompt + completion when not reported.

        Args:
            data: Raw usage mapping from the provider response, or ``None``.
            model: Model identifier to record on the resulting usage.

        Returns:
            A :class:`TokenUsage`, or ``None`` when ``data`` is not a mapping or
            contains no usable token counts.
        """
        if not isinstance(data, dict):
            return None
        prompt_tokens = _safe_int(data.get("prompt_tokens", data.get("prompt_eval_count")))
        completion_tokens = _safe_int(data.get("completion_tokens", data.get("eval_count")))
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
    def from_dict(cls, data: dict[str, Any] | None) -> TokenUsage:
        """Rebuild usage from a previously serialized mapping.

        Args:
            data: Mapping produced by :meth:`to_dict`, or ``None``.

        Returns:
            A :class:`TokenUsage` populated from ``data``, or a zeroed instance
            when ``data`` is not a mapping.
        """
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
        """Whether any non-zero token count is present."""
        return self.total_tokens > 0 or self.prompt_tokens > 0 or self.completion_tokens > 0

    def add(self, other: TokenUsage | None) -> None:
        """Accumulate another usage into this one in place.

        No-ops when ``other`` is ``None`` or has no available counts. The most
        recent non-empty ``model``/``source`` win, and ``estimated`` becomes
        ``True`` if either side is estimated.

        Args:
            other: Usage to fold into this instance.

        Returns:
            None. This instance is modified in place.
        """
        if other is None or not other.available:
            return
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens or (other.prompt_tokens + other.completion_tokens)
        self.model = other.model or self.model
        self.source = other.source or self.source
        self.estimated = self.estimated or other.estimated

    def to_dict(self) -> dict[str, Any]:
        """Serialize this usage to a JSON-friendly mapping.

        Returns:
            A mapping with the token counts plus ``model``, ``source``,
            ``estimated`` and the derived ``available`` flag.
        """
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
        """Clear per-turn counters, leaving the running session total intact."""
        self.last_call = None
        self.turn = TokenUsage()
        self.calls = []

    def hydrate_session(self, data: dict[str, Any] | None) -> None:
        """Seed the session total from persisted state, if not already set.

        Args:
            data: Persisted mapping, typically produced by :meth:`to_dict`. The
                session total is read from ``session_total``/``total`` or the
                mapping itself. Ignored when not a mapping.

        Returns:
            None. This instance is modified in place.
        """
        if not isinstance(data, dict):
            return
        session_total = data.get("session_total") or data.get("total") or data
        loaded = TokenUsage.from_dict(session_total)
        if loaded.available and not self.session.available:
            self.session = loaded

    def record_call(self, usage: TokenUsage | None) -> None:
        """Record one model call's usage into the turn and session totals.

        No-ops when ``usage`` is ``None`` or has no available counts.

        Args:
            usage: Usage reported for a single model call.

        Returns:
            None. This instance is modified in place.
        """
        if usage is None or not usage.available:
            return
        self.last_call = usage
        self.turn.add(usage)
        self.session.add(usage)
        self.calls.append(usage)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full accounting state to a JSON-friendly mapping.

        Returns:
            A mapping with ``last_call`` (or ``None``), ``last_turn``,
            ``session_total`` and the per-call ``calls`` list.
        """
        return {
            "last_call": self.last_call.to_dict() if self.last_call else None,
            "last_turn": self.turn.to_dict(),
            "session_total": self.session.to_dict(),
            "calls": [usage.to_dict() for usage in self.calls],
        }


def format_token_usage_line(state: TokenUsageState) -> str:
    """Format a one-line, human-readable token-usage summary.

    Args:
        state: Token accounting state whose turn and session totals are shown.

    Returns:
        A single line summarizing input/output/turn/conversation tokens and the
        model, or a not-available message when the current turn has no counts.
    """
    turn = state.turn
    session = state.session
    if not turn.available:
        return "Tokens: not available from the provider"
    model = turn.model or session.model or "?"
    return (
        "Tokens: "
        f"input {turn.prompt_tokens:,} | "
        f"output {turn.completion_tokens:,} | "
        f"turn {turn.total_tokens:,} | "
        f"conversation {session.total_tokens:,} | "
        f"model {model}"
    )


def _safe_int(value: Any) -> int:
    """Coerce a value to a non-negative int, returning 0 on failure."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
