"""Tipos de decision de seguridad compartidos."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DecisionAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


@dataclass(frozen=True)
class SecurityDecision:
    action: DecisionAction
    reason: str
    outcome: str | None = None
    message: str | None = None
    matched_rule: str | None = None
    external_directory: bool = False
