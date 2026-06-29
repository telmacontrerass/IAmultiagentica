"""Invoke workspace skills.

A skill is a named markdown playbook discovered in the workspace. Invoking one
returns its rendered body (plus a header with name, description and any
arguments) for injection into the agent context. Two entry points are provided:
``invoke_skill`` for model-driven invocation (which honours
``disable_model_invocation``) and ``invoke_skill_for_repl`` for explicit
user-issued slash commands (which does not).
"""

from __future__ import annotations

from ci2lab.harness.skills.loader import Skill, get_skill, load_skills
from ci2lab.harness.types import AgentConfig


def invoke_skill(config: AgentConfig, skill_name: str, args: str | None = None) -> str:
    """Resolve a workspace skill by name and render it for the agent.

    Args:
        config: Active agent configuration; ``config.cwd`` locates the skills
            and ``config.skill_allowed_tools`` may be narrowed by the skill.
        skill_name: Name of the skill to invoke.
        args: Optional user-supplied arguments appended to the rendered header.

    Returns:
        The rendered skill (header followed by its body) on success, or a
        human-readable ``Error:`` string if the skill is unknown or is flagged
        as user-invocable only.
    """
    skills = load_skills(config.cwd)
    skill = get_skill(skills, skill_name)
    if skill is None:
        available = ", ".join(sorted(skills)) or "(none)"
        return f"Error: unknown skill `{skill_name}`. Available: {available}"

    if skill.disable_model_invocation:
        return (
            f"Error: skill `{skill_name}` is user-invocable only "
            f"(disable-model-invocation: true). Use /{skill_name} in the REPL."
        )

    if skill.allowed_tools:
        config.skill_allowed_tools = frozenset(skill.allowed_tools)

    header = f"# Skill: {skill.name}\n\n{skill.description}\n"
    if args and str(args).strip():
        header += f"\n**User arguments:** {args.strip()}\n"
    if skill.allowed_tools:
        header += (
            "\n**Allowed tools for this skill:** "
            + ", ".join(f"`{t}`" for t in skill.allowed_tools)
            + "\n"
        )
    return f"{header}\n{skill.body}"


def invoke_skill_for_repl(config: AgentConfig, skill_name: str, args: str = "") -> str:
    """Render a skill for an explicit REPL slash command.

    Unlike :func:`invoke_skill`, this ignores ``disable_model_invocation`` since
    the invocation is user-initiated.

    Args:
        config: Active agent configuration; ``config.cwd`` locates the skills
            and ``config.skill_allowed_tools`` may be narrowed by the skill.
        skill_name: Name of the skill to invoke.
        args: Optional arguments appended to the rendered prefix.

    Returns:
        The rendered skill (prefix followed by its body), or a short
        ``Unknown skill`` message if no such skill exists.
    """
    skills = load_skills(config.cwd)
    skill = get_skill(skills, skill_name)
    if skill is None:
        return f"Unknown skill `{skill_name}`."
    if skill.allowed_tools:
        config.skill_allowed_tools = frozenset(skill.allowed_tools)
    prefix = f"# Skill: {skill.name}\n\n"
    if args.strip():
        prefix += f"Arguments: {args.strip()}\n\n"
    return prefix + skill.body
