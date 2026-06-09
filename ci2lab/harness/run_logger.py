"""
Logging estructurado de ejecuciones del arnés en runs/.

Los fallos de escritura no interrumpen el agente; solo emiten un aviso.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from rich.console import Console

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult

_console = Console()
LOG_OUTPUT_MAX_CHARS = 2000

RunStatus = str  # success | llm_error | max_rounds | interrupted


@dataclass
class ToolCallLogEntry:
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


@dataclass
class RunLogger:
    """Persiste artefactos de una ejecución en runs/<timestamp>_<id>/."""

    runs_dir: Path
    selection: ModelSelection
    agent_config: AgentConfig
    config_snapshot: dict[str, Any]
    user_prompt: str

    _run_dir: Path | None = field(default=None, init=False, repr=False)
    _active: bool = field(default=True, init=False, repr=False)
    _started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc), init=False
    )
    _tool_entries: list[ToolCallLogEntry] = field(default_factory=list, init=False)
    _rounds_completed: int = field(default=0, init=False)

    @classmethod
    def maybe_create(
        cls,
        agent_config: AgentConfig,
        selection: ModelSelection,
        user_prompt: str,
    ) -> RunLogger | None:
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
        if not self._active:
            return None
        try:
            short_id = uuid4().hex[:8]
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            self._run_dir = self.runs_dir / f"{stamp}_{short_id}"
            self._run_dir.mkdir(parents=True, exist_ok=False)
            self._write_json("config_snapshot.json", self.config_snapshot)
            return self._run_dir
        except Exception as exc:  # noqa: BLE001
            self._deactivate(f"No se pudo crear la carpeta de run: {exc}")
            return None

    def set_rounds_completed(self, round_num: int) -> None:
        self._rounds_completed = round_num

    def record_tool_call(
        self,
        *,
        round_num: int,
        call: ToolCall,
        result: ToolResult,
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        if not self._active or self._run_dir is None:
            return
        duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
        output = result.content
        truncated = len(output) > LOG_OUTPUT_MAX_CHARS
        if truncated:
            output = output[:LOG_OUTPUT_MAX_CHARS] + "… (truncado en log)"
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
        )
        self._tool_entries.append(entry)
        try:
            line = json.dumps(asdict(entry), ensure_ascii=False)
            path = self._run_dir / "tool_calls.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:  # noqa: BLE001
            self._warn(f"No se pudo registrar tool call: {exc}")

    def finalize(
        self,
        *,
        status: RunStatus,
        final_answer: str,
        conversation: list[dict[str, Any]],
        error: str | None = None,
    ) -> None:
        if not self._active or self._run_dir is None:
            return
        ended_at = datetime.now(timezone.utc)
        duration_s = (ended_at - self._started_at).total_seconds()
        tools_used = sorted({e.tool for e in self._tool_entries})
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
            "rounds": self._rounds_completed,
            "tool_call_count": len(self._tool_entries),
            "tools_used": tools_used,
            "status": status,
            "error": error,
            "user_prompt": self.user_prompt,
            "run_dir": str(self._run_dir),
        }
        try:
            self._write_json("run_summary.json", summary)
            self._write_json("conversation.json", {"messages": conversation})
            (self._run_dir / "final_answer.md").write_text(
                final_answer or "",
                encoding="utf-8",
            )
            _console.print(f"[dim]Run guardado: {self._run_dir}[/dim]")
        except Exception as exc:  # noqa: BLE001
            self._warn(f"No se pudo finalizar el log de ejecución: {exc}")

    def _write_json(self, name: str, data: Any) -> None:
        if self._run_dir is None:
            return
        path = self._run_dir / name
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _deactivate(self, message: str) -> None:
        self._active = False
        self._run_dir = None
        self._warn(message)

    @staticmethod
    def _warn(message: str) -> None:
        _console.print(f"[yellow]Aviso (run log): {message}[/yellow]")


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def build_config_snapshot(
    *,
    runtime_fields: dict[str, Any],
    agent_config: AgentConfig,
    selection: ModelSelection,
) -> dict[str, Any]:
    """Snapshot seguro de configuración efectiva (sin secretos ni env completo)."""
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
