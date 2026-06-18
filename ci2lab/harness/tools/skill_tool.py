"""Invoke workspace skills."""

from __future__ import annotations

from ci2lab.harness.skills.loader import Skill, get_skill, load_skills
from ci2lab.harness.types import AgentConfig


def invoke_skill(config: AgentConfig, skill_name: str, args: str | None = None) -> str:
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
    """REPL slash command — ignores disable_model_invocation."""
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
