"""Subagent execution helpers."""

from __future__ import annotations

from dataclasses import replace

from ci2lab.console import console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.multiagent.roles import ROLE_SPECS, RoleSpec
from ci2lab.harness.multiagent.state import AgentRole, SubAgentResult
from ci2lab.harness.prompts import build_system_prompt
from ci2lab.harness.query.loop import run_agent
from ci2lab.harness.types import AgentConfig


def _resolve_subagent_allowed_tools(
    role: AgentRole,
    config: AgentConfig,
) -> frozenset[str]:
    """Never let a subagent broaden an active skill allow-list."""
    role_allowed_tools = ROLE_SPECS[role].allowed_tools
    if config.skill_allowed_tools is None:
        return role_allowed_tools
    return frozenset(config.skill_allowed_tools & role_allowed_tools)


def build_role_anchor(role: AgentRole) -> str:
    """Build a short English role anchor for reinjection after tool rounds."""
    spec = ROLE_SPECS[role]
    return _role_anchor_from_spec(spec)


def _role_anchor_from_spec(spec: RoleSpec) -> str:
    return (
        f"Role anchor: You are currently acting as {spec.role.value}. "
        f"Your purpose in this phase is: {spec.phase_purpose} "
        f"Stay within this role. {spec.must_not} "
        "If blocked, report why instead of switching roles. "
        f"Expected output: {spec.expected_output}"
    )


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
        "## Role Anchor\n"
        f"{_role_anchor_from_spec(spec)}\n\n"
        "You are running with an isolated subagent context. Use only the "
        "information provided in this task prompt and any context you gather "
        "with your allowed tools."
    )


def build_subagent_config(
    role: AgentRole,
    config: AgentConfig,
) -> AgentConfig:
    """Copy the parent config and apply role-specific tool restrictions."""
    return replace(
        config,
        stream=False,
        session_id=None,
        skill_allowed_tools=_resolve_subagent_allowed_tools(role, config),
        role_anchor=build_role_anchor(role),
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
