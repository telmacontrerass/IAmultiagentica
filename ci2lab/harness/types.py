"""Tipos internos del arnes (no forman parte del contrato publico)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from ci2lab.harness.token_usage import TokenUsageState

if TYPE_CHECKING:
    from ci2lab.security.opencode_permissions import OpenCodePermissionConfig
    from ci2lab.settings import ToolSettings


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
    """approved | denied | blocked_by_config | blocked_by_security_profile | failed"""


@dataclass
class AgentConfig:
    """Configuracion de una ejecucion del arnes."""

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
    """Persistir artefactos de la ejecucion en runs/."""

    runs_dir: str = "runs"
    """Directorio base para logs de ejecucion."""

    config_snapshot: dict[str, Any] | None = None
    """Config efectiva para config_snapshot.json (sin secretos)."""

    write_tools_enabled: bool = True
    """Si False, write_file y edit_file devuelven error sin ejecutar."""

    require_diff_preview: bool = True
    """Si True, write/edit siempre muestran diff y piden confirmacion (--yes no omite)."""

    security_profile: str = "standard"
    """Perfil de seguridad (strict, standard, dev, audit)."""

    security_engine: str = "claude_experimental"
    """Motor de seguridad: claude_experimental (default), ci2lab (legacy) u opencode_experimental."""

    opencode_permissions: OpenCodePermissionConfig | None = None
    """Reglas permission estilo OpenCode (solo motor experimental)."""

    skill_allowed_tools: frozenset[str] | None = None
    """When set by an invoked skill, only these tool names are exposed to the model."""

    role_anchor: str | None = None
    """English role-discipline anchor reinjected for subagents after tool rounds."""

    tool_settings: ToolSettings | None = None
    """Reglas allow/deny de settings.json (fusionadas global + proyecto).
    Si es None, no se aplican reglas de settings y todo esta permitido."""

    token_usage: TokenUsageState = field(default_factory=TokenUsageState)
    """Contadores de tokens del turno y de la sesion actual."""
