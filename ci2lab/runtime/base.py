"""Lifecycle contracts for optional local model servers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RuntimeEndpoint:
    base_url: str
    model_id: str
    port: int


@dataclass(frozen=True)
class RuntimeHealth:
    healthy: bool
    health_status: int | None = None
    models_status: int | None = None
    error: str | None = None


class ModelRuntime(Protocol):
    def start(self) -> RuntimeEndpoint: ...
    def health_check(self) -> RuntimeHealth: ...
    def stop(self) -> None: ...
