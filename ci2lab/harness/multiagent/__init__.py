"""Sequential multi-agent orchestration primitives."""

from __future__ import annotations

from ci2lab.harness.multiagent.intent import (
    MultiAgentIntent,
    MultiAgentIntentDecision,
    classify_multiagent_intent,
)
from ci2lab.harness.multiagent.orchestrator import run_multi_agent
from ci2lab.harness.multiagent.roles import ROLE_SPECS, RoleSpec
from ci2lab.harness.multiagent.runner import run_subagent
from ci2lab.harness.multiagent.state import (
    AgentRole,
    MultiAgentRun,
    SubAgentResult,
)

__all__ = [
    "ROLE_SPECS",
    "AgentRole",
    "MultiAgentIntent",
    "MultiAgentIntentDecision",
    "MultiAgentRun",
    "RoleSpec",
    "SubAgentResult",
    "classify_multiagent_intent",
    "run_multi_agent",
    "run_subagent",
]
