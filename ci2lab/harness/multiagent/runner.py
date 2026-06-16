"""Subagent execution helpers."""

from __future__ import annotations

from dataclasses import replace

from ci2lab.console import console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.multiagent.roles import ROLE_SPECS
from ci2lab.harness.multiagent.state import AgentRole, SubAgentResult
from ci2lab.harness.prompts import build_system_prompt
from ci2lab.harness.query.loop import run_agent
from ci2lab.harness.types import AgentConfig


def build_subagent_system_prompt(
    role: AgentRole,
    selection: ModelSelection,
    config: AgentConfig,
) -> str:
    """Build an isolated system prompt for a role-specific subagent."""
    spec = ROLE_SPECS[role]
    base_prompt = build_system_prompt(selection, config.cwd)
    return (
        f"{base_prompt}\n\n"
        "## Subagent Role\n"
        f"- Role: {spec.role.value}\n"
        f"- Description: {spec.description}\n"
        f"- Can write files: {'yes' if spec.can_write else 'no'}\n\n"
        "## Role Instructions\n"
        f"{spec.system_instructions}\n\n"
        "You are running with an isolated subagent context. Use only the "
        "information provided in this task prompt and any context you gather "
        "with your allowed tools."
    )


def build_subagent_config(
    role: AgentRole,
    config: AgentConfig,
) -> AgentConfig:
    """Copy the parent config and apply role-specific tool restrictions."""
    spec = ROLE_SPECS[role]
    return replace(
        config,
        stream=False,
        session_id=None,
        skill_allowed_tools=spec.allowed_tools,
    )


def run_subagent(
    role: AgentRole,
    task_prompt: str,
    selection: ModelSelection,
    config: AgentConfig,
    *,
    attempt: int = 1,
    capture_output: bool = True,
) -> SubAgentResult:
    """Execute one role-specific subagent with its own message context."""
    subagent_config = build_subagent_config(role, config)
    system_prompt = build_subagent_system_prompt(role, selection, subagent_config)
    messages = [{"role": "system", "content": system_prompt}]

    if capture_output:
        with console.capture():
            output = run_agent(
                task_prompt,
                selection,
                config=subagent_config,
                messages=messages,
            )
    else:
        output = run_agent(
            task_prompt,
            selection,
            config=subagent_config,
            messages=messages,
        )

    return SubAgentResult(
        role=role,
        task=task_prompt,
        output=output,
        status="completed",
        attempt=attempt,
    )
