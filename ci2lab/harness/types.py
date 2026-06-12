"""Tipos internos del arnés (no forman parte del contrato público)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ToolCall:
    """Llamada a herramienta normalizada (native o parsed)."""

    name: str
    arguments: dict[str, Any]
    call_id: str | None = None


@dataclass
class ToolResult:
    """Resultado de ejecutar una herramienta."""

    tool_name: str
    content: str
    is_error: bool = False
    call_id: str | None = None
    outcome: str | None = None
    """approved | denied | blocked_by_config | failed"""


@dataclass
class AgentConfig:
    """Configuración de una ejecución del arnés."""

    cwd: str
    max_rounds: int = 25
    max_tool_output_chars: int = 10_000
    bash_timeout_seconds: int = 60
    auto_confirm: bool = False
    stream: bool = True
    """Mostrar tokens del modelo en tiempo real."""

    session_id: str | None = None
    """Si se define, persiste el historial al finalizar cada turno."""

    confirm_callback: Callable[[str, str], bool] | None = None

    run_log_enabled: bool = True
    """Persistir artefactos de la ejecución en runs/."""

    runs_dir: str = "runs"
    """Directorio base para logs de ejecución."""

    config_snapshot: dict[str, Any] | None = None
    """Config efectiva para config_snapshot.json (sin secretos)."""

    write_tools_enabled: bool = True
    """Si False, write_file y edit_file devuelven error sin ejecutar."""

    require_diff_preview: bool = True
    """Si True, write/edit siempre muestran diff y piden confirmación (--yes no omite)."""

    skill_allowed_tools: frozenset[str] | None = None
    """When set by an invoked skill, only these tool names are exposed to the model."""
