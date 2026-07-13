"""
Structured logging of harness runs in runs/.

Write failures do not interrupt the agent; they only emit a warning.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ci2lab.console import console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.token_usage import TokenUsage
from ci2lab.harness.tool_metrics import summarize_tool_calls
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult
from ci2lab.security.audit import AuditPersistContext, set_audit_persist_context
from ci2lab.security.session_permissions import (
    bind_active_session,
    clear_session_permissions,
)

LOG_OUTPUT_MAX_CHARS = 2000

RunStatus = str  # success | llm_error | max_rounds | interrupted


@dataclass
class ToolCallLogEntry:
    """One serialized record of a tool call for the run log."""

    round: int
    tool_call_id: str
    tool: str
    arguments: dict[str, Any]
    started_at: str
    ended_at: str
    duration_ms: int
    ok: bool
    output: str
    error: str | None = None
    outcome: str | None = None
    repaired: bool = False
    """True when the harness fixed the model's payload to make this call valid."""


@dataclass
class ToolParseFailureEntry:
    """One tool-call attempt that never reached execution.

    A malformed payload or an invented tool name produces no tool call, so without
    this record the attempt is invisible and the tool-call correctness denominator
    is silently too small. Written to ``tool_parse_failures.jsonl`` — a separate
    file, so ``tool_calls.jsonl`` keeps meaning "calls that actually ran".
    """

    round: int
    kind: str
    """``unparsed`` (payload unreadable) or ``unknown_tool`` (invented tool name)."""

    tool: str | None = None
    """The invented tool name, when one could be identified."""

    excerpt: str = ""


@dataclass
class TokenUsageLogEntry:
    """One serialized record of per-round token usage for the run log."""

    round: int
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    source: str
    estimated: bool


@dataclass
class RunLogger:
    """Persists artifacts of a run in runs/<timestamp>_<id>/."""

    runs_dir: Path
    selection: ModelSelection
    agent_config: AgentConfig
    config_snapshot: dict[str, Any]
    user_prompt: str

    _run_dir: Path | None = field(default=None, init=False, repr=False)
    _active: bool = field(default=True, init=False, repr=False)
    _started_at: datetime = field(default_factory=lambda: datetime.now(UTC), init=False)
    _tool_entries: list[ToolCallLogEntry] = field(default_factory=list, init=False)
    _parse_failures: list[ToolParseFailureEntry] = field(default_factory=list, init=False)
    _token_entries: list[TokenUsageLogEntry] = field(default_factory=list, init=False)
    _rounds_completed: int = field(default=0, init=False)
    _tokens_prompt_last: int = field(default=0, init=False, repr=False)
    _tokens_prompt_peak: int = field(default=0, init=False, repr=False)
    _tokens_completion_total: int = field(default=0, init=False, repr=False)

    @classmethod
    def maybe_create(
        cls,
        agent_config: AgentConfig,
        selection: ModelSelection,
        user_prompt: str,
    ) -> RunLogger | None:
        """Create a :class:`RunLogger` when run logging is enabled.

        Args:
            agent_config: The agent configuration controlling logging.
            selection: The resolved model selection for the run.
            user_prompt: The user's prompt for the run.

        Returns:
            A configured :class:`RunLogger`, or ``None`` when run logging is
            disabled.
        """
        if not agent_config.run_log_enabled:
            return None
        snapshot = agent_config.config_snapshot or {}
        return cls(
            runs_dir=Path(agent_config.runs_dir),
            selection=selection,
            agent_config=agent_config,
            config_snapshot=snapshot,
            user_prompt=user_prompt,
        )

    def start(self) -> Path | None:
        """Create the run directory and bind the run's permission/audit context.

        Only a top-level run (``delegation_depth == 0``) binds the shared audit
        context and permission session; subagents reuse the parent's.

        Returns:
            The created run directory, or ``None`` if the logger is inactive or
            the directory could not be created (in which case the logger is
            deactivated).
        """
        if not self._active:
            return None
        try:
            short_id = uuid4().hex[:8]
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            self._run_dir = self.runs_dir / f"{stamp}_{short_id}"
            self._run_dir.mkdir(parents=True, exist_ok=False)
            self.agent_config.last_run_dir = str(self._run_dir)
            self._write_json("config_snapshot.json", self.config_snapshot)
            # Only the top-level run owns the audit context and permission
            # session. A subagent (delegation_depth > 0) must NOT rebind them:
            # doing so gives each subagent its own session key, so a user's
            # "allow session" granted in one role never carries to the next, and
            # the subagent's finalize would clear the parent's grants. Leaving
            # the parent's context in place means every subagent in a multi-agent
            # run shares one permission session (one prompt, not one per role).
            if self.agent_config.delegation_depth == 0:
                set_audit_persist_context(
                    AuditPersistContext(
                        workspace=self.agent_config.cwd,
                        runs_dir=self.agent_config.runs_dir,
                        run_id=self._run_dir.name,
                        run_subdir=self._run_dir.name,
                        security_engine=self.agent_config.security_engine,
                    )
                )
                bind_active_session(self.agent_config.session_id or self._run_dir.name)
            return self._run_dir
        except Exception as exc:
            self._deactivate(f"Could not create the run folder: {exc}")
            return None

    def set_rounds_completed(self, round_num: int) -> None:
        """Record the number of rounds completed so far.

        Args:
            round_num: The count of completed rounds.
        """
        self._rounds_completed = round_num

    def record_token_stats(
        self,
        *,
        tokens_prompt_last: int,
        tokens_prompt_peak: int,
        tokens_completion_total: int,
    ) -> None:
        """Records the real token counters returned by Ollama.

        Args:
            tokens_prompt_last: Prompt tokens for the most recent round.
            tokens_prompt_peak: Highest prompt-token count seen across rounds.
            tokens_completion_total: Cumulative completion tokens generated.
        """
        self._tokens_prompt_last = tokens_prompt_last
        self._tokens_prompt_peak = tokens_prompt_peak
        self._tokens_completion_total = tokens_completion_total

    def record_tool_call(
        self,
        *,
        round_num: int,
        call: ToolCall,
        result: ToolResult,
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        """Append a tool-call record to ``tool_calls.jsonl``.

        No-op when the logger is inactive or has no run directory. Output is
        truncated to ``LOG_OUTPUT_MAX_CHARS``; write failures only warn.

        Args:
            round_num: The round in which the call occurred.
            call: The tool call that was executed.
            result: The result returned by the tool.
            started_at: When the call started.
            ended_at: When the call ended.
        """
        if not self._active or self._run_dir is None:
            return
        duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
        output = result.content
        truncated = len(output) > LOG_OUTPUT_MAX_CHARS
        if truncated:
            output = output[:LOG_OUTPUT_MAX_CHARS] + "… (truncated in log)"
        outcome = result.outcome or ("approved" if not result.is_error else "failed")
        entry = ToolCallLogEntry(
            round=round_num,
            tool_call_id=call.call_id or result.call_id or "",
            tool=call.name,
            arguments=call.arguments,
            started_at=_iso(started_at),
            ended_at=_iso(ended_at),
            duration_ms=duration_ms,
            ok=not result.is_error,
            output=output,
            error=result.content if result.is_error else None,
            outcome=outcome,
            repaired=call.repaired,
        )
        self._tool_entries.append(entry)
        try:
            line = json.dumps(asdict(entry), ensure_ascii=False)
            path = self._run_dir / "tool_calls.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:
            self._warn(f"Could not record tool call: {exc}")

    def record_parse_failure(
        self,
        *,
        round_num: int,
        kind: str,
        excerpt: str,
        tool: str | None = None,
    ) -> None:
        """Append a failed tool-call attempt to ``tool_parse_failures.jsonl``.

        These attempts never reach :meth:`record_tool_call` — the payload could not
        be parsed, or it named a tool that does not exist — so without this record
        they leave no trace and the tool-call correctness rate is computed over too
        small a denominator. No-op when the logger is inactive or has no run
        directory; write failures only warn.

        Args:
            round_num: The round in which the attempt occurred.
            kind: ``"unparsed"`` or ``"unknown_tool"``.
            excerpt: The offending model output (truncated for the log).
            tool: The invented tool name, when one could be identified.
        """
        if not self._active or self._run_dir is None:
            return
        entry = ToolParseFailureEntry(
            round=round_num,
            kind=kind,
            tool=tool,
            excerpt=excerpt[:LOG_OUTPUT_MAX_CHARS],
        )
        self._parse_failures.append(entry)
        try:
            line = json.dumps(asdict(entry), ensure_ascii=False)
            path = self._run_dir / "tool_parse_failures.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:
            self._warn(f"Could not record tool parse failure: {exc}")

    def record_token_usage(self, *, round_num: int, usage: TokenUsage | None) -> None:
        """Append a token-usage record to ``token_usage.jsonl``.

        No-op when the logger is inactive, has no run directory, or ``usage`` is
        missing/unavailable. Write failures only warn.

        Args:
            round_num: The round the usage corresponds to.
            usage: The token-usage data to record, if any.
        """
        if not self._active or self._run_dir is None or usage is None or not usage.available:
            return
        entry = TokenUsageLogEntry(
            round=round_num,
            model=usage.model or self.selection.ollama_tag,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            source=usage.source,
            estimated=usage.estimated,
        )
        self._token_entries.append(entry)
        try:
            line = json.dumps(asdict(entry), ensure_ascii=False)
            path = self._run_dir / "token_usage.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:
            self._warn(f"Could not record token usage: {exc}")

    def finalize(
        self,
        *,
        status: RunStatus,
        final_answer: str,
        conversation: list[dict[str, Any]],
        error: str | None = None,
    ) -> None:
        """Write the run summary and conversation, then tear down shared context.

        Aggregates tool and token statistics into ``run_summary.json``, writes
        ``conversation.json`` and ``final_answer.md``, and—for a top-level run
        only—clears the shared permission session and audit context. No-op when
        the logger is inactive or has no run directory.

        Args:
            status: Final run status (e.g. ``success``, ``max_rounds``).
            final_answer: The agent's final answer text.
            conversation: The full conversation to persist.
            error: Optional error message associated with the run.
        """
        if not self._active or self._run_dir is None:
            return
        ended_at = datetime.now(UTC)
        duration_s = (ended_at - self._started_at).total_seconds()
        tools_used = sorted({e.tool for e in self._tool_entries})
        prompt_tokens = sum(e.prompt_tokens for e in self._token_entries)
        completion_tokens = sum(e.completion_tokens for e in self._token_entries)
        total_tokens = sum(e.total_tokens for e in self._token_entries)
        ctx_len = self.selection.context_length or 0
        tokens_available = self._tokens_prompt_peak > 0
        context_used_pct = (
            round(self._tokens_prompt_peak / ctx_len * 100, 1)
            if tokens_available and ctx_len
            else None
        )
        summary = {
            "started_at": _iso(self._started_at),
            "ended_at": _iso(ended_at),
            "duration_seconds": round(duration_s, 3),
            "model": self.selection.ollama_tag,
            "model_id": self.selection.model_id,
            "backend_url": self.selection.backend_url,
            "tool_mode": self.selection.tool_mode,
            "workspace": self.agent_config.cwd,
            "max_rounds": self.agent_config.max_rounds,
            "stream": self.agent_config.stream,
            "auto_confirm": self.agent_config.auto_confirm,
            "write_tools_enabled": self.agent_config.write_tools_enabled,
            "require_diff_preview": self.agent_config.require_diff_preview,
            "verify_final_answer": self.agent_config.verify_final_answer,
            "rounds": self._rounds_completed,
            "tool_call_count": len(self._tool_entries),
            "tool_call_quality": summarize_tool_calls(
                self._tool_entries, self._parse_failures
            ).to_dict(),
            "tools_used": tools_used,
            "token_usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "call_count": len(self._token_entries),
                "available": total_tokens > 0,
                "source": "provider",
                "estimated": False,
            },
            "status": status,
            "error": error,
            "user_prompt": self.user_prompt,
            "run_dir": str(self._run_dir),
            "tokens": {
                "available": tokens_available,
                "prompt_last_round": self._tokens_prompt_last,
                "prompt_peak": self._tokens_prompt_peak,
                "completion_total": self._tokens_completion_total,
                "context_length": ctx_len,
                "context_used_pct": context_used_pct,
            },
        }
        try:
            self._write_json("run_summary.json", summary)
            self._write_json("conversation.json", {"messages": conversation})
            (self._run_dir / "final_answer.md").write_text(
                final_answer or "",
                encoding="utf-8",
            )
            if not self.agent_config.suppress_run_saved_message:
                console.print(f"[dim]Run saved: {self._run_dir}[/dim]")
        except Exception as exc:
            self._warn(f"Could not finalize the run log: {exc}")
        finally:
            # Mirror start(): only the top-level run tears down the shared
            # permission session and audit context. A subagent clearing them
            # would wipe approvals the rest of the multi-agent run still needs.
            if self.agent_config.delegation_depth == 0:
                session_key = self.agent_config.session_id or (
                    self._run_dir.name if self._run_dir is not None else None
                )
                if session_key:
                    clear_session_permissions(session_key)
                bind_active_session(None)
                set_audit_persist_context(None)

    def _write_json(self, name: str, data: Any) -> None:
        """Write ``data`` as pretty-printed JSON to ``name`` in the run directory."""
        if self._run_dir is None:
            return
        path = self._run_dir / name
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @property
    def run_dir(self) -> Path | None:
        """The run directory, or ``None`` if not started or deactivated."""
        return self._run_dir

    def write_json_artifact(self, name: str, data: Any) -> None:
        """Write an arbitrary JSON artifact into the run directory.

        Args:
            name: File name to write within the run directory.
            data: JSON-serializable data to persist.
        """
        self._write_json(name, data)

    def _deactivate(self, message: str) -> None:
        """Disable the logger, drop the run directory, and warn ``message``."""
        self._active = False
        self._run_dir = None
        self._warn(message)

    @staticmethod
    def _warn(message: str) -> None:
        """Print a yellow run-log warning to the console."""
        console.print(f"[yellow]Warning (run log): {message}[/yellow]")


def _iso(dt: datetime) -> str:
    """Return ``dt`` as an ISO-8601 string, assuming UTC if it is naive."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def build_config_snapshot(
    *,
    runtime_fields: dict[str, Any],
    agent_config: AgentConfig,
    selection: ModelSelection,
) -> dict[str, Any]:
    """Safe snapshot of the effective configuration (no secrets, no full env).

    Args:
        runtime_fields: Extra resolved runtime fields to include verbatim.
        agent_config: The agent configuration to snapshot.
        selection: The resolved model selection to snapshot.

    Returns:
        A nested mapping with ``resolved`` and ``selection`` sections describing
        the effective configuration.
    """
    return {
        "resolved": {
            **runtime_fields,
            "cwd": agent_config.cwd,
            "max_rounds": agent_config.max_rounds,
            "stream": agent_config.stream,
            "auto_confirm": agent_config.auto_confirm,
            "run_log_enabled": agent_config.run_log_enabled,
            "runs_dir": agent_config.runs_dir,
            "write_tools_enabled": agent_config.write_tools_enabled,
            "require_diff_preview": agent_config.require_diff_preview,
            "verify_final_answer": agent_config.verify_final_answer,
        },
        "selection": {
            "model_id": selection.model_id,
            "ollama_tag": selection.ollama_tag,
            "display_name": selection.display_name,
            "backend_url": selection.backend_url,
            "tool_mode": selection.tool_mode,
            "supports_tools": selection.supports_tools,
            "context_length": selection.context_length,
            "max_tokens": selection.max_tokens,
            "temperature": selection.temperature,
        },
    }
