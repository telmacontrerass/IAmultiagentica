"""Shared security decision types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DecisionAction(str, Enum):
    """Outcome of a security evaluation for a single tool call.

    Attributes:
        ALLOW: The tool may run without confirmation.
        DENY: The tool is blocked and must not run.
        CONFIRM: The tool may run only after explicit user approval.
    """

    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


@dataclass(frozen=True)
class SecurityDecision:
    """Immutable result of evaluating a tool call against a security policy.

    Attributes:
        action: The decision action (allow, deny or confirm).
        reason: Machine-readable reason code for the decision.
        outcome: Optional outcome label recorded in the audit log.
        message: Optional human-readable message (typically for denials).
        matched_rule: Identifier of the rule that produced the decision.
        external_directory: True if the target lies outside the workspace.
    """

    action: DecisionAction
    reason: str
    outcome: str | None = None
    message: str | None = None
    matched_rule: str | None = None
    external_directory: bool = False
