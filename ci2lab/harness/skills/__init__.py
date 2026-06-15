"""Workspace skills — `.ci2lab/skills/*/SKILL.md` discovery and catalog formatting."""

from ci2lab.harness.skills.loader import (
    Skill,
    format_skill_catalog,
    get_skill,
    load_skills,
    skills_for_model,
)

__all__ = [
    "Skill",
    "format_skill_catalog",
    "get_skill",
    "load_skills",
    "skills_for_model",
]
