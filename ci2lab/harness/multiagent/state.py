"""State types for multi-agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgentRole(str, Enum):
    """Predefined subagent roles supported by the orchestrator."""

    PLANNER = "planner"
    RESEARCHER = "researcher"
    PYTHON_CODER = "python_coder"
    FRONTEND_CODER = "frontend_coder"
    TEST_CODER = "test_coder"
    DOCS_CODER = "docs_coder"
    GENERALIST_CODER = "generalist_coder"
    VALIDATOR = "validator"
    REVIEWER = "reviewer"
    SECURITY_REVIEWER = "security_reviewer"


@dataclass
class SubAgentResult:
    """Result produced by a subagent with its own isolated context."""

    role: AgentRole
    task: str
    output: str
    status: str = "completed"
    attempt: int = 1


@dataclass
class MultiAgentRun:
    """Shared orchestration state, controlled only by the orchestrator."""

    user_prompt: str
    results: list[SubAgentResult] = field(default_factory=list)
    selected_coder_role: AgentRole | None = None
    final_answer: str | None = None

    def add_result(self, result: SubAgentResult) -> None:
        self.results.append(result)

    def latest_for(self, role: AgentRole) -> SubAgentResult | None:
        for result in reversed(self.results):
            if result.role == role:
                return result
        return None
