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
